#!/usr/bin/env python3
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def candidate_urls(url: str) -> list[str]:
    urls = [url]
    if url.startswith("https://"):
        urls.append("http://" + url[len("https://") :])
    elif url.startswith("http://"):
        urls.append("https://" + url[len("http://") :])
    return list(dict.fromkeys(urls))


def download_one(item: dict, work_dir: Path, retries: int, timeout: int) -> tuple[int, str, int]:
    index = int(item["index"])
    path = Path(item.get("path") or work_dir / f"image_{index:02d}.jpg")
    if not path.is_absolute():
        path = work_dir / path
    item["path"] = str(path)
    if path.exists() and path.stat().st_size > 0:
        return index, "skip", path.stat().st_size

    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.xiaohongshu.com/"}
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        for url in candidate_urls(item["url"]):
            try:
                tmp = path.with_suffix(path.suffix + ".part")
                with requests.get(url, headers=headers, timeout=(10, timeout), stream=True) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(65536):
                            if chunk:
                                handle.write(chunk)
                tmp.replace(path)
                return index, "ok", path.stat().st_size
            except Exception as exc:
                errors.append(f"attempt {attempt} {url}: {exc}")
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"image {index:02d} failed after retries; last error: {errors[-1] if errors else 'unknown'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Xiaohongshu note images from manifest.json.")
    parser.add_argument("--manifest", required=True, help="path to manifest.json from resolve_note.py")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    work_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images", [])
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = [executor.submit(download_one, item, work_dir, args.retries, args.timeout) for item in images]
        for future in as_completed(futures):
            try:
                index, status, size = future.result()
                print(f"{index:02d} {status} {size}")
            except Exception as exc:
                failures.append(str(exc))
                print(str(exc), file=sys.stderr)

    downloaded = 0
    for item in images:
        path = Path(item.get("path", ""))
        if path.exists() and path.stat().st_size > 0:
            downloaded += 1
    manifest["downloaded_count"] = downloaded
    manifest["download_errors"] = failures
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if failures:
        print(f"downloaded {downloaded}/{len(images)} images; failures: {len(failures)}", file=sys.stderr)
        return 2
    print(f"downloaded {downloaded}/{len(images)} images", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
