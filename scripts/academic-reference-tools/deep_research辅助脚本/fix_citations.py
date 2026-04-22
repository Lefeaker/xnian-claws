#!/usr/bin/env python3
"""Normalize reference lines and inline numeric citations in Markdown files."""

from __future__ import annotations

import re
from pathlib import Path

RAW_REF_LINE_RE = re.compile(
    r"^(?P<num>\d+)\.\s+(?P<rest>.+?)\s*\[(?P<url>https?://[^\]]+)\]\((?P=url)\)\s*$"
)
MD_REF_LINE_RE = re.compile(
    r"^(?P<num>\d+)\.\s+\[(?P<title>.+?)\]\((?P<url>https?://[^\)]+)\)\s*$"
)
ACCESS_SUFFIX_RE = re.compile(
    r"(,?\s*accessed\s+.+?\s*|[，,]?\s*访问时间为\s*.+?\s*)$",
    re.IGNORECASE,
)
INLINE_CITE_RE = re.compile(r"[\t \u00A0](?P<num>\d{1,3})。")


def normalize_references(text: str) -> tuple[str, dict[str, str], bool]:
    lines = text.splitlines()
    ref_map: dict[str, str] = {}
    changed = False
    new_lines: list[str] = []

    for line in lines:
        raw_match = RAW_REF_LINE_RE.match(line)
        md_match = MD_REF_LINE_RE.match(line)

        if raw_match:
            num = raw_match.group("num")
            rest = raw_match.group("rest")
            url = raw_match.group("url")
            title = ACCESS_SUFFIX_RE.sub("", rest).strip()
        elif md_match:
            num = md_match.group("num")
            title = ACCESS_SUFFIX_RE.sub("", md_match.group("title")).strip()
            url = md_match.group("url")
        else:
            new_lines.append(line)
            continue

        if not title:
            new_lines.append(line)
            continue

        ref_map[num] = url
        new_line = f"{num}. [{title}]({url})"
        if new_line != line:
            changed = True
        new_lines.append(new_line)

    return "\n".join(new_lines), ref_map, changed


def replace_inline_citations(text: str, ref_map: dict[str, str]) -> tuple[str, bool]:
    if not ref_map:
        return text, False

    def repl(match: re.Match[str]) -> str:
        num = match.group("num")
        url = ref_map.get(num)
        if not url:
            return match.group(0)
        return f"[{num}]({url})。"

    new_text = INLINE_CITE_RE.sub(repl, text)
    return new_text, new_text != text


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    normalized, ref_map, changed_refs = normalize_references(text)
    updated, changed_inline = replace_inline_citations(normalized, ref_map)

    if changed_refs or changed_inline:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> None:
    md_files = [p for p in Path(".").rglob("*.md") if p.is_file()]
    changed_files = 0

    for path in md_files:
        if process_file(path):
            changed_files += 1

    print(f"Updated {changed_files} Markdown file(s).")


if __name__ == "__main__":
    main()
