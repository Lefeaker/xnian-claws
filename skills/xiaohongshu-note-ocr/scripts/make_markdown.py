#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


CORRECTIONS = {
    "訟盈余": "论盈余",
    "Minerv": "Minerva",
    "无法这个现象": "无法为这个现象",
    "并非是因\n": "并非是因为\n",
    "卽": "即",
    "眞": "真",
    "喜悅": "喜悦",
    "會": "会",
    "一朶": "一朵",
    "看淸": "看清",
    "认某些": "认为某些",
    "认这份": "认为这份",
    "一种特的本体论属性": "一种特殊的本体论属性",
    "被视异端": "被视为异端",
    "雨化一种": "雨化为一种",
    "盈余什么发生": "盈余为什么发生",
    "作认识论学者": "作为认识论学者",
    "“": "“",
    "”": "”",
}


def safe_filename(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:max_len].strip("._") or "xiaohongshu_note"


def apply_corrections(text: str) -> str:
    for wrong, right in CORRECTIONS.items():
        text = text.replace(wrong, right)
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    return text


def extract_ocr_lines(markdown: str) -> list[str]:
    blocks = re.findall(r"```text\n(.*?)\n```", markdown, flags=re.S)
    body = "\n\n".join(blocks) if blocks else markdown
    body = re.sub(r"^# .*$", "", body, flags=re.M)
    body = re.sub(r"^- .*$", "", body, flags=re.M)
    body = re.sub(r"^## 图 \d+.*$", "", body, flags=re.M)
    return [line.strip() for line in body.splitlines()]


def paragraphize(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current = ""
    force_starters = (
        "独自时",
        "与她在一起时",
        "和她在一起时",
        "八月",
        "九月",
        "十月",
        "十一月",
        "我想说的是",
        "以及",
    )

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        line = re.sub(r"^[◎○oO]\s*", "", line)

        starts_new = line.startswith(force_starters)
        previous_ends = bool(current and re.search(r"[。！？：；]$|[.!?]$", current))
        if current and (starts_new or previous_ends):
            paragraphs.append(current)
            current = line
        else:
            current = current + line if current else line

    if current:
        paragraphs.append(current)
    return paragraphs


def clean_ocr_markdown(markdown: str, title: str | None = None, source_url: str | None = None) -> str:
    markdown = apply_corrections(markdown)
    lines = extract_ocr_lines(markdown)
    paragraphs = paragraphize(lines)

    if title:
        title = apply_corrections(title).strip()
    else:
        title_match = re.search(r"^#\s+(.+?)\s+OCR\s*$", markdown, flags=re.M)
        title = title_match.group(1).strip() if title_match else "小红书笔记"

    # Drop OCR title duplicates from the body if they appear after heading extraction.
    normalized_title = re.sub(r"\s+", "", title)
    filtered: list[str] = []
    for paragraph in paragraphs:
        compact = re.sub(r"\s+", "", paragraph)
        if compact == normalized_title or compact.endswith("OCR"):
            continue
        filtered.append(paragraph)

    output = [f"# {title}", ""]
    if source_url:
        output.extend([f"来源：{source_url}", ""])
    output.extend(filtered)
    text = "\n\n".join(output).strip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def verify_work_dir(work_dir: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []
    manifest_path = work_dir / "manifest.json"
    if not manifest_path.exists():
        return False, ["missing manifest.json"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images", [])
    missing = []
    for image in images:
        path = Path(image.get("path") or work_dir / f"image_{int(image['index']):02d}.jpg")
        if not path.is_absolute():
            path = work_dir / path
        if not path.exists() or path.stat().st_size == 0:
            missing.append(f"{int(image['index']):02d}")
    if missing:
        messages.append(f"missing images: {', '.join(missing)}")
    else:
        messages.append(f"images ok: {len(images)}")

    raw_files = sorted(work_dir.glob("*_OCR.md"))
    if raw_files:
        raw_text = raw_files[0].read_text(encoding="utf-8")
        sections = len(re.findall(r"^## 图 \d+", raw_text, flags=re.M))
        if sections != len(images):
            messages.append(f"raw OCR sections {sections} != images {len(images)}")
        else:
            messages.append(f"raw OCR sections ok: {sections}")

    proofread_files = sorted(work_dir.glob("*人工校对稿.md"))
    for file in proofread_files:
        text = file.read_text(encoding="utf-8")
        if "## 图" in text:
            messages.append(f"{file.name} still contains page markers")
        if "\ufffd" in text:
            messages.append(f"{file.name} contains replacement characters")
    failed = False
    for msg in messages:
        if msg.startswith("missing"):
            failed = True
        if "!=" in msg:
            failed = True
        if "contains" in msg:
            failed = True
    return not failed, messages


def command_clean(args: argparse.Namespace) -> int:
    ocr_path = Path(args.ocr).expanduser()
    text = ocr_path.read_text(encoding="utf-8")
    cleaned = clean_ocr_markdown(text, title=args.title, source_url=args.source_url)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(cleaned, encoding="utf-8")
    print(output)
    return 0


def command_verify(args: argparse.Namespace) -> int:
    ok, messages = verify_work_dir(Path(args.work_dir).expanduser())
    for message in messages:
        print(message)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean and verify Xiaohongshu OCR Markdown.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean = subparsers.add_parser("clean", help="convert raw OCR Markdown into a continuous draft")
    clean.add_argument("--ocr", required=True)
    clean.add_argument("--output", required=True)
    clean.add_argument("--title")
    clean.add_argument("--source-url")
    clean.set_defaults(func=command_clean)

    verify = subparsers.add_parser("verify", help="verify a Xiaohongshu OCR work directory")
    verify.add_argument("--work-dir", required=True)
    verify.set_defaults(func=command_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
