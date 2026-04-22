#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 /path/to/input.docx /path/to/output_dir"
  echo "Example: $0 /path/to/thesis.docx /path/to/output_dir"
  exit 1
fi

in_docx="$1"
out_dir="$2"

if [ ! -f "$in_docx" ]; then
  echo "Input DOCX not found: $in_docx" >&2
  exit 1
fi

mkdir -p "$out_dir"

base_name="$(basename "$in_docx")"
md_name="${base_name%.*}.md"
md_out="$out_dir/$md_name"
img_dir="$out_dir/files/${base_name%.*}"

mkdir -p "$img_dir"

tmpdir=$(mktemp -d)

pandoc "$in_docx" -t gfm --wrap=none -o "$md_out" --extract-media="$tmpdir"

if [ -d "$tmpdir/media" ]; then
  cp -R "$tmpdir/media/." "$img_dir/"
fi

rm -rf "$tmpdir"

# Convert WMF to PNG and delete WMF
if command -v wmf2gd >/dev/null 2>&1; then
  for f in "$img_dir"/*.wmf; do
    [ -e "$f" ] || continue
    out="${f%.wmf}.png"
    wmf2gd -o "$out" "$f"
    rm -f "$f"
  done
fi

MD_OUT="$md_out" python3 - <<'PY'
import re, shlex
import os
from pathlib import Path

md_path = Path(os.environ["MD_OUT"])
text = md_path.read_text(encoding='utf-8')
asset_prefix = f"files/{md_path.stem}"

# Replace HTML img tags with markdown image links to basename
img_tag = re.compile(r'<img\s+[^>]*?src="([^"]+)"[^>]*?>', re.I)
text = img_tag.sub(lambda m: f"![]({asset_prefix}/{m.group(1).split('/')[-1]})", text)

# Convert Obsidian embeds to standard markdown image links with basename
text = re.sub(r'!\[\[([^\]]+)\]\]', lambda m: f"![]({asset_prefix}/{m.group(1).split('/')[-1]})", text)

# Convert markdown image links to basename only
img_pattern = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

def img_repl(m):
    raw = m.group(1).strip()
    if raw.startswith('<') and raw.endswith('>'):
        path = raw[1:-1].strip()
    else:
        try:
            parts = shlex.split(raw)
            path = parts[0] if parts else raw
        except ValueError:
            path = raw.split()[0]
        path = path.strip().strip('"\'')
    name = path.split('/')[-1]
    if name.lower().endswith('.wmf'):
        name = name[:-4] + '.png'
    final_path = f"{asset_prefix}/{name}"
    if any(ch in final_path for ch in " '()"):
        return f"![](<{final_path}>)"
    return f"![]({final_path})"

text = img_pattern.sub(img_repl, text)

# Fix headings from anchor spans
lines = text.splitlines()
new_lines = []
span_re = re.compile(r'^\s*<span\s+id="([^"]+)"\s+class="anchor"></span>\s*(.*)\s*$')

def heading_level(title: str) -> int:
    t = title.strip()
    if not t:
        return 1
    top = {"摘 要", "摘要", "Abstract", "关键词", "Key Words", "目 录", "参考文献", "参 考 文 献", "致谢", "附录", "结论", "结 论", "Summary"}
    if t in top:
        return 1
    if re.match(r'^第.+章', t):
        return 1
    if re.match(r'^\d+\.\d+\.\d+', t):
        return 3
    if re.match(r'^\d+\.\d+', t):
        return 2
    if re.match(r'^\d+\s', t):
        return 2
    return 1

for line in lines:
    m = span_re.match(line)
    if m:
        title = m.group(2).strip()
        if title:
            level = heading_level(title)
            new_lines.append('#' * level + ' ' + title)
        else:
            continue
    else:
        new_lines.append(line)

text = "\n".join(new_lines)

# Promote bolded 目录 to heading if present
text = text.replace('**目 录**', '# 目 录')

# Convert in-text HTML superscript references: <sup>[27]</sup> -> [^27]
text = re.sub(r'<sup>\\?\[(\d+)\\?\]</sup>', r'[^\1]', text)

# Convert reference list entries within references section to footnotes
lines = text.splitlines()
new_lines = []
ref_heading_re = re.compile(r'^#+\s*(参\s*考\s*文\s*献|参考文献)\s*$')
ref_line_re = re.compile(r'^\\?\[(\d+)\\?\]\s*(.*)$')

in_refs = False
for line in lines:
    if ref_heading_re.match(line.strip()):
        in_refs = True
        new_lines.append(line)
        continue
    if in_refs:
        m = ref_line_re.match(line)
        if m:
            new_lines.append(f"[^%s]: %s" % (m.group(1), m.group(2)))
            continue
    new_lines.append(line)

md_path.write_text("\n".join(new_lines), encoding='utf-8')
PY

echo "Done: $md_out"
