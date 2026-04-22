import re
import sys
from urllib.parse import urlsplit

LINK_RE = re.compile(r"\[\[?([^\]]+)\]?\]\(([^)]+)\)")


def normalize_url(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def split_reference_section(text):
    match = re.search(r"^\*\*参考文献.*\*\*\s*$", text, flags=re.MULTILINE)
    if not match:
        separators = list(re.finditer(r"^---\s*$", text, flags=re.MULTILINE))
        for separator in reversed(separators):
            refs = text[separator.end():].strip()
            if len(LINK_RE.findall(refs)) >= 2:
                body = text[:separator.start()].rstrip()
                return body, refs
        return text, ""
    body = text[:match.start()].rstrip()
    refs = text[match.end():].strip()
    return body, refs


def strip_four_asterisks(text):
    return text.replace("****", "")


def normalize_label(label):
    return label.strip().strip("[]").strip()


def is_numeric_label(label):
    return normalize_label(label).isdigit()


def strip_trailing_numbered_block(body):
    lines = body.splitlines()
    idx = len(lines)
    while idx > 0 and not lines[idx - 1].strip():
        idx -= 1
    while idx > 0 and re.match(r"^\s*\d+\.\s+", lines[idx - 1]):
        idx -= 1
        while idx > 0 and not lines[idx - 1].strip():
            idx -= 1
    return "\n".join(lines[:idx]).rstrip()


def parse_reference_blocks(ref_text):
    if not ref_text:
        return []
    blocks = re.split(r"\n\s*\n", ref_text.strip())
    entries = []
    seen = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", block, flags=re.DOTALL)
        content = m.group(1) if m else block
        content = " ".join(line.strip() for line in content.splitlines())
        links = LINK_RE.findall(content)
        if not links:
            continue
        main_url = links[0][1].strip()
        non_citation_labels = []
        for label, url in links:
            cleaned = normalize_label(label)
            if cleaned and not cleaned.isdigit() and cleaned != url:
                non_citation_labels.append(cleaned)

        content_no_links = LINK_RE.sub("", content)
        content_no_links = re.sub(r"https?://\S+", "", content_no_links).strip()
        parts = re.split(r"\s+–\s+|\s+-\s+", content_no_links, maxsplit=1)
        title = non_citation_labels[0] if non_citation_labels else parts[0].strip()
        if not title:
            title = main_url
        description = parts[1].strip() if len(parts) > 1 else ""
        key = normalize_url(main_url)
        if key in seen:
            entry = seen[key]
            entry["links"].extend(u for _, u in links)
            if not entry["description"] and description:
                entry["description"] = description
            if entry["title"] == entry["url"] and title != main_url:
                entry["title"] = title
            continue
        entry = {
            "title": title,
            "url": main_url,
            "description": description,
            "links": [u for _, u in links],
        }
        entries.append(entry)
        seen[key] = entry
    return entries


def replace_inline_links(body, ref_map, entries):
    def repl(match):
        label = match.group(1).strip()
        url = match.group(2).strip()
        if url.startswith("#"):
            return match.group(0)
        key = normalize_url(url)
        if is_numeric_label(label):
            if key not in ref_map:
                new_id = len(entries) + 1
                ref_map[key] = new_id
                entries.append(
                    {"title": url, "url": url, "description": "", "links": [url]}
                )
            return f"[{ref_map[key]}]({url})"
        if key not in ref_map:
            new_id = len(entries) + 1
            ref_map[key] = new_id
            entries.append(
                {"title": label or url, "url": url, "description": "", "links": [url]}
            )
        return f"[{ref_map[key]}]({url})"
    return LINK_RE.sub(repl, body)


def build_reference_text(entries):
    lines = ["**参考文献：**", ""]
    for idx, entry in enumerate(entries, start=1):
        title = entry["title"]
        url = entry["url"]
        description = entry["description"]
        line = f"{idx}. [{title}]({url})"
        if description:
            line += f" – {description}"
        lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def process_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    content = strip_four_asterisks(content)
    body, ref_text = split_reference_section(content)
    body = strip_trailing_numbered_block(body)
    entries = parse_reference_blocks(ref_text)

    ref_map = {}
    for idx, entry in enumerate(entries, start=1):
        for link in entry["links"]:
            ref_map[normalize_url(link)] = idx

    new_body = replace_inline_links(body, ref_map, entries)
    new_content = new_body.rstrip() + "\n\n" + build_reference_text(entries)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Successfully processed {path}")
    print(f"Total references: {len(entries)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_reference_list.py <file_path>")
        sys.exit(1)
    process_file(sys.argv[1])
