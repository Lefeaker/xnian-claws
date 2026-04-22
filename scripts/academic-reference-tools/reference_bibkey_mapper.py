#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import bibtexparser
except Exception:
    bibtexparser = None

from obsidian_bib_extractor import DEFAULT_STRATEGY_CONFIG, MetadataFetcher, SQLiteCache, normalize_doi

W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DOI_INLINE_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract reference list from DOCX/XML or Markdown, match against a BibTeX library, and write [@citekey] annotations into a Markdown copy."
    )
    parser.add_argument("--source-md", required=True, help="Markdown file to annotate or use as source")
    parser.add_argument("--source-docx", help="Optional DOCX file whose Word XML bibliography will be used as the reference source")
    parser.add_argument("--bib", required=True, help="Existing BibTeX library to match against")
    parser.add_argument("--output-copy", required=True, help="Path for annotated Markdown copy")
    parser.add_argument("--mapping-json", required=True, help="JSON output for reference to BibKey mapping")
    parser.add_argument("--mapping-txt", required=True, help="Text output for reference to BibKey mapping")
    parser.add_argument("--cache", default="ref_bibkey_mapper_cache.sqlite", help="SQLite cache path")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--trust-env-proxy", action="store_true")
    parser.add_argument("--skip-crossref", action="store_true", help="Skip Crossref online lookup and only use strict local matching")
    return parser.parse_args()


def clean_reference_text(text: str) -> str:
    text = unescape(text)
    text = HTML_TAG_RE.sub("", text)
    text = text.replace("\\[", "[").replace("\\]", "]")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_title(text: str) -> str:
    text = clean_reference_text(text).lower()
    text = re.sub(r"\[[A-Za-z]\]", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_title_guess(reference: str) -> str | None:
    cleaned = clean_reference_text(reference)
    marker_match = re.search(r"\[[A-Za-z]\]", cleaned)
    left = cleaned[: marker_match.start()].strip().rstrip(".") if marker_match else cleaned
    if ". " in left:
        title = left.split(". ", 1)[1].strip().rstrip(".")
    elif "．" in left:
        title = left.split("．", 1)[1].strip().rstrip("．")
    else:
        title = left
    title = re.sub(r"^\[\d+\]\s*", "", title).strip()
    return title if len(title) >= 8 else None


def extract_first_author_token(reference: str) -> str:
    cleaned = clean_reference_text(reference)
    head = re.split(r"\.\s+|．", cleaned, maxsplit=1)[0].strip()
    if not head:
        return ""
    if "，" in head:
        token = head.split("，", 1)[0].strip()
    else:
        token = head.split(",", 1)[0].strip()
    if re.search(r"[A-Za-z]", token):
        token = token.split()[0]
    token = re.sub(r"[^A-Za-z\u4e00-\u9fff-]", "", token).lower()
    return token


def extract_reference_year(reference: str) -> str:
    match = YEAR_RE.search(reference)
    return match.group(0) if match else ""


def extract_refs_from_docx(path: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    for para in root.findall(".//w:p", W_NS):
        pstyle = para.find("./w:pPr/w:pStyle", W_NS)
        if pstyle is None:
            continue
        if pstyle.attrib.get("{%s}val" % W_NS["w"]) != "EndNoteBibliography":
            continue
        text = "".join(node.text or "" for node in para.findall(".//w:t", W_NS)).strip()
        text = clean_reference_text(text)
        if not text:
            continue
        match = re.match(r"^\[(\d+)\]\s*(.+)$", text)
        if not match:
            continue
        refs.append({"index": int(match.group(1)), "reference": match.group(2).strip(), "source": "docx_xml"})
    refs.sort(key=lambda item: item["index"])
    return refs


def extract_refs_from_markdown(path: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        footnote = re.match(r"^\\?\[\^(\d+)\]:\s*(.+)$", text)
        if footnote:
            refs.append({"index": int(footnote.group(1)), "reference": clean_reference_text(footnote.group(2)), "source": "markdown_footnote"})
            continue
        bracket = re.match(r"^\\?\[(\d+)\\?\]\s*(.+)$", text)
        if bracket:
            refs.append({"index": int(bracket.group(1)), "reference": clean_reference_text(bracket.group(2)), "source": "markdown_bracket"})
    refs.sort(key=lambda item: item["index"])
    return refs


def load_bib_entries(path: Path) -> list[dict[str, Any]]:
    if not bibtexparser:
        raise SystemExit("Missing dependency bibtexparser. Please install requirements.txt")
    with path.open(encoding="utf-8") as handle:
        db = bibtexparser.load(handle)
    return [dict(entry) for entry in db.entries]


def build_bib_index(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    doi_map: dict[str, dict[str, Any]] = {}
    title_map: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        doi = normalize_doi(str(entry.get("doi", ""))) if entry.get("doi") else None
        if doi:
            doi_map[doi] = entry
        title_norm = normalize_title(str(entry.get("title", "")))
        if title_norm:
            title_map.setdefault(title_norm, []).append(entry)
    return doi_map, title_map


def select_candidate(candidates: list[dict[str, Any]], reference: str) -> tuple[dict[str, Any] | None, str]:
    if not candidates:
        return None, ""

    ref_year = extract_reference_year(reference)
    pool = [c for c in candidates if not ref_year or str(c.get("year", "")).strip() == ref_year] or candidates

    unique_ids = []
    seen_ids = set()
    for candidate in pool:
        candidate_id = str(candidate.get("ID", "")).strip()
        if candidate_id and candidate_id not in seen_ids:
            seen_ids.add(candidate_id)
            unique_ids.append(candidate)

    if len(unique_ids) == 1:
        return unique_ids[0], "title_exact"

    fingerprints = {
        (
            normalize_title(str(c.get("title", ""))),
            str(c.get("year", "")).strip(),
            normalize_doi(str(c.get("doi", ""))) if c.get("doi") else "",
        )
        for c in unique_ids
    }
    if len(fingerprints) == 1 and unique_ids:
        return unique_ids[0], "title_exact_duplicate"

    return None, ""


def match_bib_entry(
    reference: str,
    fetcher: MetadataFetcher | None,
    doi_map: dict[str, dict[str, Any]],
    title_map: dict[str, list[dict[str, Any]]],
    *,
    skip_crossref: bool = False,
) -> tuple[dict[str, Any] | None, str | None, str]:
    inline = DOI_INLINE_RE.search(reference)
    if inline:
        doi = normalize_doi(inline.group(0))
        if doi and doi in doi_map:
            return doi_map[doi], doi, "inline_doi"

    title_guess = extract_title_guess(reference)
    if title_guess:
        title_norm = normalize_title(title_guess)
        candidate, method = select_candidate(title_map.get(title_norm, []), reference)
        if candidate:
            doi = normalize_doi(str(candidate.get("doi", ""))) if candidate.get("doi") else None
            return candidate, doi, method

    if skip_crossref or fetcher is None:
        return None, None, "unmatched"

    query = re.sub(r"\s+", " ", reference).strip()
    doi = fetcher._search_crossref_doi_by_bibliographic(query)
    if doi and doi in doi_map:
        return doi_map[doi], doi, "crossref_bibliographic"

    if title_guess:
        doi = fetcher._search_crossref_doi_by_title(title_guess)
        if doi and doi in doi_map:
            return doi_map[doi], doi, "crossref_title"

    return None, None, "unmatched"


def append_mapping_section(text: str, rows: list[dict[str, Any]]) -> str:
    section_title = "## 参考文献 CiteKey 对照"
    lines = [section_title, ""]
    for row in rows:
        cite = f"[@{row['bibkey']}]" if row.get("bibkey") else "[UNMATCHED]"
        lines.append(f"[{row['index']}] {row['reference']} {cite}")
        lines.append("")
    block = "\n".join(lines).rstrip() + "\n"
    if section_title in text:
        text = text.split(section_title, 1)[0].rstrip() + "\n\n" + block
    else:
        text = text.rstrip() + "\n\n" + block
    return text


def annotate_reference_lines(text: str, rows: list[dict[str, Any]]) -> tuple[str, int]:
    rows_by_reference: dict[str, list[dict[str, Any]]] = {}
    rows_by_index: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_reference.setdefault(row["reference"], []).append(row)
        rows_by_index.setdefault(int(row["index"]), []).append(row)

    out_lines = []
    annotated_count = 0
    for line in text.splitlines():
        footnote = re.match(r"^(\\?\[\^(\d+)\]:\s*(.+?))(\s*\[@[^\]]+\])?$", line)
        if footnote:
            ref_text = clean_reference_text(footnote.group(3))
            candidates = rows_by_reference.get(ref_text, [])
            row = candidates.pop(0) if candidates else None
            if row is None:
                candidates = rows_by_index.get(int(footnote.group(2)), [])
                row = candidates.pop(0) if candidates else None
            if row and row.get("bibkey"):
                out_lines.append(f"{footnote.group(1)} [@{row['bibkey']}]")
                annotated_count += 1
            else:
                out_lines.append(line)
            continue

        bracket = re.match(r"^(\\?\[(\d+)\\?\]\s*(.+?))(\s*\[@[^\]]+\])?$", line)
        if bracket:
            ref_text = clean_reference_text(bracket.group(3))
            candidates = rows_by_reference.get(ref_text, [])
            row = candidates.pop(0) if candidates else None
            if row is None:
                candidates = rows_by_index.get(int(bracket.group(2)), [])
                row = candidates.pop(0) if candidates else None
            if row and row.get("bibkey"):
                out_lines.append(f"{bracket.group(1)} [@{row['bibkey']}]")
                annotated_count += 1
            else:
                out_lines.append(line)
            continue

        out_lines.append(line)
    return "\n".join(out_lines).rstrip() + "\n", annotated_count

def main() -> int:
    args = parse_args()
    source_md = Path(args.source_md).expanduser().resolve()
    source_docx = Path(args.source_docx).expanduser().resolve() if args.source_docx else None
    bib_path = Path(args.bib).expanduser().resolve()
    output_copy = Path(args.output_copy).expanduser().resolve()
    mapping_json = Path(args.mapping_json).expanduser().resolve()
    mapping_txt = Path(args.mapping_txt).expanduser().resolve()
    cache_path = Path(args.cache).expanduser().resolve()

    refs = extract_refs_from_docx(source_docx) if source_docx else extract_refs_from_markdown(source_md)
    if not refs:
        raise SystemExit("No reference list entries found from the provided source")

    bib_entries = load_bib_entries(bib_path)
    doi_map, title_map = build_bib_index(bib_entries)

    fetcher = None
    if not args.skip_crossref:
        fetcher = MetadataFetcher(
            cache=SQLiteCache(cache_path),
            dry_run=False,
            verbose=False,
            timeout=args.timeout,
            max_retries=max(1, args.max_retries),
            skip_url_fetch=False,
            trust_env_proxy=args.trust_env_proxy,
            strategy_config=DEFAULT_STRATEGY_CONFIG,
        )

    rows: list[dict[str, Any]] = []
    try:
        for ref in refs:
            entry, doi, match_method = match_bib_entry(
                ref["reference"],
                fetcher,
                doi_map,
                title_map,
                skip_crossref=args.skip_crossref,
            )
            rows.append(
                {
                    "index": ref["index"],
                    "reference": ref["reference"],
                    "reference_source": ref["source"],
                    "doi": doi,
                    "bibkey": entry.get("ID") if entry else None,
                    "title": entry.get("title") if entry else None,
                    "match_method": match_method,
                    "matched": bool(entry),
                }
            )
    finally:
        if fetcher is not None:
            fetcher.close()
            fetcher.cache.close()

    source_text = source_md.read_text(encoding="utf-8", errors="ignore")
    annotated, annotated_count = annotate_reference_lines(source_text, rows)
    if annotated_count == 0:
        annotated = append_mapping_section(source_text, rows)
    output_copy.write_text(annotated, encoding="utf-8")

    mapping_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "source_md": str(source_md),
        "source_docx": str(source_docx) if source_docx else None,
        "bib": str(bib_path),
        "output_copy": str(output_copy),
        "total_refs": len(rows),
        "matched": sum(1 for row in rows if row["matched"]),
        "unmatched": sum(1 for row in rows if not row["matched"]),
    }
    text_lines = [f"{key}: {value}" for key, value in summary.items()]
    text_lines.append("")
    for row in rows:
        text_lines.append(
            f'[{row["index"]}] {"MATCH" if row["matched"] else "MISS"} citekey={row.get("bibkey") or ""} doi={row.get("doi") or ""} method={row["match_method"]} {row["reference"]}'
        )
    mapping_txt.write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
