#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from obsidian_bib_extractor import DEFAULT_STRATEGY_CONFIG, MetadataFetcher, SQLiteCache, normalize_doi

API_BASE = "http://127.0.0.1:23119"
USER_API_BASE = f"{API_BASE}/api/users/0"
CONNECTOR_SAVE_ITEMS = f"{API_BASE}/connector/saveItems"
AUTO_TAG = "obsidian-bib-importer-auto"


def api_get_json(url: str):
    with urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def connector_post(payload: dict) -> tuple[int, str]:
    body_payload = dict(payload)
    body_payload["sessionID"] = f"codex-{uuid.uuid4().hex}"
    req = Request(
        CONNECTOR_SAVE_ITEMS,
        data=json.dumps(body_payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        return exc.code, body


def connector_get_selected_collection() -> dict:
    req = Request(
        f"{API_BASE}/connector/getSelectedCollection",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import failed extractor URLs into Zotero (metadata first, webpage fallback)"
    )
    p.add_argument("--report", default="extraction_report.json")
    p.add_argument("--cache", default="cache.sqlite")
    p.add_argument("--target-collection-name", default="Imported from Obsidian")
    p.add_argument("--fallback-collection-name", default="Webpage fallback")
    p.add_argument("--out", default="zotero_import_report.json")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--trust-env-proxy", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--skip-non-scholarly-hosts",
        action="store_true",
        default=True,
        help="Skip obvious non-scholarly hosts before any metadata fetch",
    )
    return p.parse_args()


def non_scholarly_hosts() -> set[str]:
    values = (
        DEFAULT_STRATEGY_CONFIG.get("heuristics", {}).get("non_scholarly_hosts", [])
        if isinstance(DEFAULT_STRATEGY_CONFIG, dict)
        else []
    )
    return {str(x).lower() for x in values if str(x).strip()}


def parse_authors(raw: str) -> list[dict]:
    creators = []
    for part in re.split(r"\s+and\s+", raw or ""):
        token = part.strip().strip("{}")
        if not token:
            continue
        if "," in token:
            last, first = [x.strip() for x in token.split(",", 1)]
        else:
            segs = token.split()
            if len(segs) == 1:
                creators.append({"name": token, "creatorType": "author"})
                continue
            first = " ".join(segs[:-1])
            last = segs[-1]
        creators.append({"firstName": first, "lastName": last, "creatorType": "author"})
    return creators


def bib_to_zotero_item(entry: dict, source_url: str) -> dict:
    et = str(entry.get("ENTRYTYPE", "")).lower()
    type_map = {
        "article": "journalArticle",
        "inproceedings": "conferencePaper",
        "proceedings": "conferencePaper",
        "book": "book",
        "phdthesis": "thesis",
        "mastersthesis": "thesis",
        "misc": "document",
    }
    item_type = type_map.get(et, "journalArticle")
    item = {"itemType": item_type}

    if entry.get("title"):
        item["title"] = str(entry.get("title"))
    if entry.get("journal"):
        item["publicationTitle"] = str(entry.get("journal"))
    if entry.get("booktitle") and item_type == "conferencePaper":
        item["proceedingsTitle"] = str(entry.get("booktitle"))
    if entry.get("year"):
        item["date"] = str(entry.get("year"))
    if entry.get("volume"):
        item["volume"] = str(entry.get("volume"))
    if entry.get("number"):
        item["issue"] = str(entry.get("number"))
    if entry.get("pages"):
        item["pages"] = str(entry.get("pages"))

    doi = normalize_doi(str(entry.get("doi", ""))) if entry.get("doi") else None
    if doi:
        item["DOI"] = doi

    url = str(entry.get("url") or source_url)
    if url:
        item["url"] = url

    creators = parse_authors(str(entry.get("author", "")))
    item["creators"] = creators
    item["tags"] = [{"tag": AUTO_TAG}]
    return item


def fallback_webpage_item(url: str, fallback_tag: str) -> dict:
    host = urlsplit(url).netloc
    return {
        "itemType": "webpage",
        "title": f"Fallback: {host}",
        "url": url,
        "tags": [{"tag": AUTO_TAG}, {"tag": fallback_tag}],
        "creators": [],
    }


def main() -> int:
    args = parse_args()

    collections = api_get_json(f"{USER_API_BASE}/collections")
    target_key = None
    fallback_key = None
    for c in collections:
        d = c.get("data", {})
        if d.get("name") == args.target_collection_name and not d.get("parentCollection"):
            target_key = d.get("key")
    if not target_key:
        raise SystemExit(f"Target collection not found: {args.target_collection_name}")

    for c in collections:
        d = c.get("data", {})
        if d.get("name") == args.fallback_collection_name and d.get("parentCollection") == target_key:
            fallback_key = d.get("key")

    selected = connector_get_selected_collection()
    selected_name = selected.get("name") or ""
    if selected_name and selected_name != args.target_collection_name:
        print(
            "Warning: Zotero connector selected collection is "
            f"{selected_name!r}, but imports will still target {args.target_collection_name!r}."
        )

    report_path = Path(args.report).expanduser().resolve()
    cache_path = Path(args.cache).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = report.get("records", report if isinstance(report, list) else [])

    failed_urls = []
    seen = set()
    skip_hosts = non_scholarly_hosts() if args.skip_non_scholarly_hosts else set()
    for rec in records:
        if rec.get("fetch_status") == "success":
            continue
        nid = str(rec.get("normalized_id") or "").strip()
        if not nid.startswith("http"):
            continue
        host = (urlsplit(nid).netloc or "").lower()
        if host in skip_hosts:
            continue
        if nid not in seen:
            seen.add(nid)
            failed_urls.append(nid)

    if args.limit > 0:
        failed_urls = failed_urls[: args.limit]

    cache = SQLiteCache(cache_path)
    fetcher = MetadataFetcher(
        cache=cache,
        dry_run=False,
        verbose=False,
        timeout=args.timeout,
        max_retries=max(1, args.max_retries),
        skip_url_fetch=False,
        trust_env_proxy=args.trust_env_proxy,
        strategy_config=DEFAULT_STRATEGY_CONFIG,
    )

    rows = []
    imported = 0
    fallback_imported = 0
    failed = 0

    for url in failed_urls:
        result = fetcher.fetch_url(url)
        row = {
            "url": url,
            "metadata_success": result.success,
            "canonical_key": result.canonical_key,
            "error": result.error,
        }

        if result.success and result.bib_entry:
            item = bib_to_zotero_item(result.bib_entry, url)
            payload = {"items": [item], "collection": target_key}
            row["mode"] = "metadata"
        else:
            item = fallback_webpage_item(url, args.fallback_collection_name)
            payload = {"items": [item], "collection": fallback_key or target_key}
            row["mode"] = "fallback_webpage"

        if args.dry_run:
            row["zotero_status"] = None
            row["zotero_body"] = "dry_run"
        else:
            status, body = connector_post(payload)
            row["zotero_status"] = status
            row["zotero_body"] = body[:500]
            if 200 <= status < 300:
                if row["mode"] == "metadata":
                    imported += 1
                else:
                    fallback_imported += 1
            else:
                failed += 1

        rows.append(row)

    summary = {
        "report": str(report_path),
        "cache": str(cache_path),
        "total_failed_urls_considered": len(failed_urls),
        "imported_metadata": imported,
        "imported_fallback_webpage": fallback_imported,
        "failed_connector_posts": failed,
        "dry_run": args.dry_run,
        "target_collection_name": args.target_collection_name,
        "fallback_collection_name": args.fallback_collection_name,
        "auto_tag": AUTO_TAG,
    }
    out = {"summary": summary, "records": rows}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
