#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

try:
    import bibtexparser
except Exception:  # pragma: no cover
    bibtexparser = None


DEFAULT_EXCLUDES = [".obsidian", ".git", "node_modules", "attachments", "Templates"]
DOI_REGEX = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", re.IGNORECASE)
URL_REGEX = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
TRAILING_PUNCT = ",.;:!?)]}>'\""
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "from",
    "source",
    "share",
    "spm",
}

MD_LINK_PATTERN = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)", re.IGNORECASE)
ANGLE_URL_PATTERN = re.compile(r"<\s*(https?://[^>\s]+)\s*>", re.IGNORECASE)
BARE_URL_PATTERN = re.compile(r"(?<!\]\()(?<!\()\bhttps?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)


@dataclass
class ReplaceStats:
    files_scanned: int = 0
    files_changed: int = 0
    links_seen: int = 0
    links_replaced: int = 0
    links_unmatched: int = 0
    ambiguous_matches: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace Obsidian hyperlinks with [@citekey] by matching a BibTeX library."
    )
    parser.add_argument("--input", required=True, help="Input directory to scan recursively")
    parser.add_argument("--bib", default="ztrreflist.bib", help="BibTeX file path")
    parser.add_argument("--report", default="cite_replace_report.json", help="JSON report output path")
    parser.add_argument("--dry-run", action="store_true", help="Preview replacements without modifying files")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Additional directory name to exclude (can repeat)",
    )
    parser.add_argument(
        "--path-contains",
        action="append",
        default=[],
        help="Only process markdown files whose relative path contains this text (can repeat). Defaults to all files.",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Ignore --path-contains filter and process all markdown files",
    )
    parser.add_argument(
        "--backup-ext",
        default="",
        help="Optional backup extension before overwrite, e.g. .bak",
    )
    return parser.parse_args()


def normalize_doi(raw: str) -> str | None:
    text = unquote(raw.strip())
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip("<>()[]{} ").rstrip(TRAILING_PUNCT).lower()

    match = DOI_REGEX.search(text)
    if not match:
        return None
    doi = match.group(0).strip().rstrip(TRAILING_PUNCT)
    doi = doi.split("?", 1)[0].split("#", 1)[0]
    doi = re.sub(r"(?i)(\.pdf|\.html?)$", "", doi)
    doi = re.sub(r"(?i)/(full|fulltext|epub|epdf|pdf|abstract)$", "", doi)
    doi = doi.rstrip(TRAILING_PUNCT)
    return doi.lower() if DOI_REGEX.fullmatch(doi) else None


def normalize_url(url: str, keep_query: bool = True) -> str | None:
    try:
        sp = urlsplit(unquote(url.strip()))
    except Exception:
        return None
    if sp.scheme.lower() not in {"http", "https"} or not sp.netloc:
        return None

    scheme = sp.scheme.lower()
    host = sp.netloc.lower()
    path = re.sub(r"/+", "/", sp.path or "")
    path = path.rstrip("/")
    if not path:
        path = "/"

    query_items = []
    if keep_query and sp.query:
        for key, value in parse_qsl(sp.query, keep_blank_values=True):
            if key.lower() in TRACKING_QUERY_KEYS:
                continue
            query_items.append((key, value))
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, host, path, query, ""))


def url_lookup_candidates(url: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    base = normalize_url(url, keep_query=True)
    bare = normalize_url(url, keep_query=False)
    add(base)
    add(bare)

    if bare:
        sp = urlsplit(bare)
        path = sp.path
        for suffix in ("/full", "/fulltext", "/abstract", "/pdf", "/epdf", "/download"):
            if path.lower().endswith(suffix):
                path2 = path[: -len(suffix)] or "/"
                add(urlunsplit((sp.scheme, sp.netloc, path2, "", "")))

    return candidates


def scan_markdown_files(root: Path, excludes: set[str], all_files: bool, contains: list[str]) -> list[Path]:
    files: list[Path] = []
    filters = [x for x in contains if x] if not all_files else []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part in excludes for part in rel.parts):
            continue
        rel_text = str(rel)
        if filters and not any(token in rel_text for token in filters):
            continue
        files.append(path)
    return files


def line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(text):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def pos_to_line(starts: list[int], pos: int) -> int:
    return bisect_right(starts, pos)


def parse_bib_file(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Bib file not found: {path}")
    if not bibtexparser:
        raise SystemExit("Missing dependency bibtexparser. Please install requirements.txt")

    with path.open("r", encoding="utf-8") as fh:
        db = bibtexparser.load(fh)
    return db.entries


def build_bib_index(entries: Iterable[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    doi_to_keys: dict[str, set[str]] = defaultdict(set)
    url_to_keys: dict[str, set[str]] = defaultdict(set)

    for entry in entries:
        key = str(entry.get("ID", "")).strip()
        if not key:
            continue

        for field, value in entry.items():
            if field in {"ID", "ENTRYTYPE"}:
                continue
            text = str(value or "")
            if not text:
                continue

            if field.lower() == "doi":
                doi = normalize_doi(text)
                if doi:
                    doi_to_keys[doi].add(key)

            for match in DOI_REGEX.finditer(text):
                doi = normalize_doi(match.group(0))
                if doi:
                    doi_to_keys[doi].add(key)

            for match in URL_REGEX.finditer(text):
                raw_url = match.group(0)
                for candidate in url_lookup_candidates(raw_url):
                    url_to_keys[candidate].add(key)
                doi = normalize_doi(raw_url)
                if doi:
                    doi_to_keys[doi].add(key)

    return doi_to_keys, url_to_keys


def select_citekey(keys: set[str]) -> tuple[str, bool]:
    ordered = sorted(keys)
    return ordered[0], len(ordered) > 1


def resolve_url(url: str, doi_to_keys: dict[str, set[str]], url_to_keys: dict[str, set[str]]) -> tuple[str | None, str, bool]:
    doi = normalize_doi(url)
    if doi and doi in doi_to_keys:
        citekey, ambiguous = select_citekey(doi_to_keys[doi])
        return citekey, "doi", ambiguous

    for candidate in url_lookup_candidates(url):
        keys = url_to_keys.get(candidate)
        if keys:
            citekey, ambiguous = select_citekey(keys)
            return citekey, "url", ambiguous

    return None, "none", False


def replace_in_text(
    text: str,
    rel_path: str,
    doi_to_keys: dict[str, set[str]],
    url_to_keys: dict[str, set[str]],
    stats: ReplaceStats,
) -> tuple[str, list[dict]]:
    events: list[dict] = []

    def record(start_pos: int, raw_url: str, citekey: str | None, method: str, ambiguous: bool) -> None:
        ln = pos_to_line(starts, start_pos)
        events.append(
            {
                "source_file": rel_path,
                "source_line": ln,
                "raw_url": raw_url,
                "matched": bool(citekey),
                "citekey": citekey,
                "method": method,
                "ambiguous": ambiguous,
            }
        )

    starts = line_starts(text)

    def sub_md(match: re.Match) -> str:
        raw_url = match.group(1)
        stats.links_seen += 1
        citekey, method, ambiguous = resolve_url(raw_url, doi_to_keys, url_to_keys)
        record(match.start(1), raw_url, citekey, method, ambiguous)
        if ambiguous:
            stats.ambiguous_matches += 1
        if citekey:
            stats.links_replaced += 1
            return f"[@{citekey}]"
        stats.links_unmatched += 1
        return match.group(0)

    text = MD_LINK_PATTERN.sub(sub_md, text)

    def sub_angle(match: re.Match) -> str:
        raw_url = match.group(1)
        stats.links_seen += 1
        citekey, method, ambiguous = resolve_url(raw_url, doi_to_keys, url_to_keys)
        record(match.start(1), raw_url, citekey, method, ambiguous)
        if ambiguous:
            stats.ambiguous_matches += 1
        if citekey:
            stats.links_replaced += 1
            return f"[@{citekey}]"
        stats.links_unmatched += 1
        return match.group(0)

    text = ANGLE_URL_PATTERN.sub(sub_angle, text)

    def sub_bare(match: re.Match) -> str:
        token = match.group(0)
        trailing_match = re.search(r"([,.;:!?]+)$", token)
        trailing = trailing_match.group(1) if trailing_match else ""
        raw_url = token[: -len(trailing)] if trailing else token

        stats.links_seen += 1
        citekey, method, ambiguous = resolve_url(raw_url, doi_to_keys, url_to_keys)
        record(match.start(0), raw_url, citekey, method, ambiguous)
        if ambiguous:
            stats.ambiguous_matches += 1
        if citekey:
            stats.links_replaced += 1
            return f"[@{citekey}]{trailing}"
        stats.links_unmatched += 1
        return token

    text = BARE_URL_PATTERN.sub(sub_bare, text)
    return text, events


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input).expanduser().resolve()
    bib_path = Path(args.bib).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")

    excluded_dirs = set(DEFAULT_EXCLUDES + list(args.exclude_dir or []))
    files = scan_markdown_files(input_dir, excluded_dirs, args.all_files, list(args.path_contains or []))

    bib_entries = parse_bib_file(bib_path)
    doi_to_keys, url_to_keys = build_bib_index(bib_entries)

    stats = ReplaceStats(files_scanned=len(files))
    all_events: list[dict] = []

    for file_path in files:
        rel_path = str(file_path.relative_to(input_dir))
        original = file_path.read_text(encoding="utf-8")
        updated, events = replace_in_text(original, rel_path, doi_to_keys, url_to_keys, stats)
        all_events.extend(events)

        if updated != original:
            stats.files_changed += 1
            if not args.dry_run:
                if args.backup_ext:
                    backup_path = file_path.with_suffix(file_path.suffix + args.backup_ext)
                    backup_path.write_text(original, encoding="utf-8")
                file_path.write_text(updated, encoding="utf-8")

        if args.verbose:
            replaced = sum(1 for event in events if event["matched"])
            if replaced:
                print(f"{rel_path}: replaced={replaced}")

    report = {
        "summary": {
            "files_scanned": stats.files_scanned,
            "files_changed": stats.files_changed,
            "links_seen": stats.links_seen,
            "links_replaced": stats.links_replaced,
            "links_unmatched": stats.links_unmatched,
            "ambiguous_matches": stats.ambiguous_matches,
            "dry_run": bool(args.dry_run),
            "input_dir": str(input_dir),
            "bib_file": str(bib_path),
            "path_contains": [] if args.all_files else list(args.path_contains or []),
        },
        "events": all_events,
    }

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "Summary: "
        f"files_scanned={stats.files_scanned}, "
        f"files_changed={stats.files_changed}, "
        f"links_seen={stats.links_seen}, "
        f"links_replaced={stats.links_replaced}, "
        f"links_unmatched={stats.links_unmatched}, "
        f"ambiguous_matches={stats.ambiguous_matches}, "
        f"dry_run={args.dry_run}"
    )
    print(f"Report output: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
