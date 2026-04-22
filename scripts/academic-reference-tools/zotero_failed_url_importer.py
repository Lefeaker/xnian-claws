#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from obsidian_bib_extractor import DEFAULT_STRATEGY_CONFIG, MetadataFetcher, SQLiteCache, normalize_doi

DEFAULT_API_BASE = "http://127.0.0.1:23119"
DEFAULT_TARGET_COLLECTION_NAME = "Imported Articles"
DEFAULT_FALLBACK_COLLECTION_NAME = "Webpage Fallback"
DEFAULT_IMPORT_TAG = "auto-imported"


def normalize_api_base(api_base: str) -> str:
    return api_base.rstrip("/")


def user_api_base(api_base: str) -> str:
    return f"{normalize_api_base(api_base)}/api/users/0"


def connector_save_items_url(api_base: str) -> str:
    return f"{normalize_api_base(api_base)}/connector/saveItems"


def connector_get_selected_collection_url(api_base: str) -> str:
    return f"{normalize_api_base(api_base)}/connector/getSelectedCollection"


def api_get_json(url: str):
    with urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def connector_post(api_base: str, payload: dict) -> tuple[int, str]:
    body_payload = dict(payload)
    body_payload["sessionID"] = f"codex-{uuid.uuid4().hex}"
    req = Request(
        connector_save_items_url(api_base),
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


def connector_get_selected_collection(api_base: str) -> dict:
    req = Request(
        connector_get_selected_collection_url(api_base),
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import failed extractor URLs into Zotero (metadata first, webpage fallback)")
    p.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help="Base URL for the local Zotero Connector API",
    )
    p.add_argument("--report", default="extraction_report.json")
    p.add_argument("--cache", default="cache_full_steady.sqlite")
    p.add_argument("--target-collection-name", default=DEFAULT_TARGET_COLLECTION_NAME)
    p.add_argument("--fallback-collection-name", default=DEFAULT_FALLBACK_COLLECTION_NAME)
    p.add_argument("--import-tag", default=DEFAULT_IMPORT_TAG, help="Tag applied to imported Zotero items")
    p.add_argument("--out", default="zotero_import_report.json")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--trust-env-proxy", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--skip-non-scholarly-hosts",
        action=argparse.BooleanOptionalAction,
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


def bib_to_zotero_item(entry: dict, source_url: str, import_tag: str) -> dict:
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
    item["tags"] = [{"tag": import_tag}]
    return item


def fallback_webpage_item(url: str, import_tag: str, fallback_tag: str) -> dict:
    host = urlsplit(url).netloc
    return {
        "itemType": "webpage",
        "title": f"Fallback: {host}",
        "url": url,
        "tags": [{"tag": import_tag}, {"tag": fallback_tag}],
        "creators": [],
    }


def main() -> int:
    args = parse_args()
    api_base = normalize_api_base(args.api_base)

    collections = api_get_json(f"{user_api_base(api_base)}/collections")
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

    selected = connector_get_selected_collection(api_base)
    targets = selected.get("targets", [])
    target_id = None
    fallback_target_id = None
    for t in targets:
        tid = str(t.get("id", ""))
        name = str(t.get("name", ""))
        if tid.startswith("C") and name == args.target_collection_name:
            target_id = tid
        if tid.startswith("C") and name == args.fallback_collection_name:
            fallback_target_id = tid

    if not target_id:
        raise SystemExit(f"Could not resolve connector target id for {args.target_collection_name}")

    with open(args.report, "r", encoding="utf-8") as f:
        records = json.load(f)

    blocked_hosts = non_scholarly_hosts() if args.skip_non_scholarly_hosts else set()

    failed_urls = []
    seen = set()
    skipped_non_scholarly = 0
    for row in records:
        if row.get("fetch_status") != "fail":
            continue
        nid = str(row.get("normalized_id") or "")
        if not nid.startswith(("http://", "https://")):
            continue
        host = (urlsplit(nid).netloc or "").lower()
        if host in blocked_hosts:
            skipped_non_scholarly += 1
            continue
        if nid in seen:
            continue
        seen.add(nid)
        failed_urls.append(nid)

    if args.limit > 0:
        failed_urls = failed_urls[: args.limit]

    cache = SQLiteCache(Path(args.cache))
    fetcher = MetadataFetcher(
        cache=cache,
        dry_run=False,
        verbose=False,
        timeout=args.timeout,
        max_retries=max(1, args.max_retries),
        trust_env_proxy=args.trust_env_proxy,
        strategy_config=None,
    )

    article_items = []
    fallback_items = []
    stats = {
        "failed_url_candidates": len(failed_urls),
        "skipped_non_scholarly": skipped_non_scholarly,
        "article_items": 0,
        "fallback_items": 0,
        "imported_article_items": 0,
        "imported_fallback_items": 0,
        "fallback_collection_found": bool(fallback_key),
        "fallback_imported_to": args.fallback_collection_name if fallback_key else args.target_collection_name,
    }

    details = []
    for url in failed_urls:
        doi_hint = normalize_doi(url)
        if doi_hint:
            result = fetcher.fetch_doi(doi_hint)
        elif any(token in url.lower() for token in ("doi.org/", "/doi/", "arxiv.org/", "pubmed.ncbi.nlm.nih.gov/")):
            result = fetcher.fetch_url(url)
        else:
            result = None

        if result and result.success and result.bib_entry:
            item = bib_to_zotero_item(result.bib_entry, url, args.import_tag)
            article_items.append(item)
            details.append({"url": url, "mode": "article"})
        else:
            item = fallback_webpage_item(url, args.import_tag, args.fallback_collection_name)
            fallback_items.append(item)
            details.append({"url": url, "mode": "fallback", "error": None if result is None else result.error})

    fetcher.close()

    stats["article_items"] = len(article_items)
    stats["fallback_items"] = len(fallback_items)

    def batch(items, size=25):
        for i in range(0, len(items), size):
            yield items[i:i+size]

    if not args.dry_run:
        for b in batch(article_items):
            code, _ = connector_post(api_base, {"target": target_id, "items": b})
            if code == 201:
                stats["imported_article_items"] += len(b)
            else:
                for item in b:
                    c2, _ = connector_post(api_base, {"target": target_id, "items": [item]})
                    if c2 == 201:
                        stats["imported_article_items"] += 1

        fb_target = fallback_target_id if fallback_target_id else target_id
        for b in batch(fallback_items):
            code, _ = connector_post(api_base, {"target": fb_target, "items": b})
            if code == 201:
                stats["imported_fallback_items"] += len(b)
            else:
                for item in b:
                    c2, _ = connector_post(api_base, {"target": fb_target, "items": [item]})
                    if c2 == 201:
                        stats["imported_fallback_items"] += 1

    out = {
        "summary": stats,
        "api_base": api_base,
        "target_collection": args.target_collection_name,
        "target_collection_key": target_key,
        "fallback_collection": args.fallback_collection_name,
        "fallback_collection_key": fallback_key,
        "details_sample": details[:300],
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False))
    print(f"report={Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
