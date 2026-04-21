#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def sanitize_filename(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:max_len].strip("._") or "xiaohongshu_note"


def normalize_state_json(raw: str) -> str:
    # Xiaohongshu state sometimes serializes JavaScript undefined values.
    return re.sub(r"(?<=[:\[,])undefined(?=[,}\]])", "null", raw)


def extract_initial_state(html: str) -> dict:
    match = re.search(r"window\.__INITIAL_STATE__=(\{.*?\})</script>", html, re.S)
    if not match:
        raise ValueError("window.__INITIAL_STATE__ not found")
    return json.loads(normalize_state_json(match.group(1)))


def find_note(state: dict) -> tuple[str, dict]:
    detail_map = state.get("note", {}).get("noteDetailMap", {})
    for note_id, payload in detail_map.items():
        note = payload.get("note") if isinstance(payload, dict) else None
        if isinstance(note, dict) and note.get("imageList"):
            return note_id, note
    raise ValueError("noteDetailMap does not contain an image note")


def pick_image_url(image: dict) -> str:
    if image.get("urlDefault"):
        return image["urlDefault"]
    for item in image.get("infoList", []):
        if item.get("imageScene") == "WB_DFT" and item.get("url"):
            return item["url"]
    for item in image.get("infoList", []):
        if item.get("url"):
            return item["url"]
    raise ValueError("image entry has no usable URL")


def resolve_note(url: str) -> tuple[str, dict]:
    session = requests.Session()
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True,
        timeout=30,
    )
    response.raise_for_status()
    state = extract_initial_state(response.text)
    note_id, note = find_note(state)
    final_url = response.url
    if "/explore/" in final_url or "/discovery/item/" in final_url:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    else:
        note_url = final_url
    return final_url, {
        "note_id": note_id,
        "note_url": note_url,
        "title": note.get("title") or "小红书笔记",
        "desc": note.get("desc") or "",
        "images": [
            {
                "index": idx,
                "url": pick_image_url(image),
                "width": image.get("width"),
                "height": image.get("height"),
            }
            for idx, image in enumerate(note.get("imageList", []), 1)
        ],
    }


def default_work_dir(download_root: Path, note_id: str) -> Path:
    return download_root.expanduser() / f"xhs_{note_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a Xiaohongshu note URL into a manifest.")
    parser.add_argument("url", help="xhslink.com or xiaohongshu.com note URL")
    parser.add_argument("--download-root", default="~/download", help="root directory for note work dirs")
    parser.add_argument("--work-dir", help="explicit work directory")
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if not parsed.scheme or not parsed.netloc:
        parser.error("url must include scheme and host")
    if "xhslink.com" not in parsed.netloc and "xiaohongshu.com" not in parsed.netloc:
        parser.error("url must be a Xiaohongshu or xhslink URL")

    try:
        final_url, note_data = resolve_note(args.url)
        work_dir = Path(args.work_dir).expanduser() if args.work_dir else default_work_dir(Path(args.download_root), note_data["note_id"])
        work_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source_url": args.url,
            "resolved_url": final_url,
            "note_id": note_data["note_id"],
            "note_url": note_data["note_url"],
            "title": note_data["title"],
            "safe_title": sanitize_filename(note_data["title"]),
            "desc": note_data["desc"],
            "image_count": len(note_data["images"]),
            "images": note_data["images"],
        }
        (work_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(work_dir)
        print(f"resolved {manifest['image_count']} images: {manifest['title']}", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"resolve_note failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
