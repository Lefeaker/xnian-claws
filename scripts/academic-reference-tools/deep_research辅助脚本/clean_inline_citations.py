import re
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "utm_name",
}


def normalize_url(url):
    parts = urlsplit(url)
    fragment = parts.fragment
    if fragment.startswith(":~:text="):
        fragment = ""
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    query_pairs = [(k, v) for k, v in query_pairs if k not in TRACKING_PARAMS]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


def strip_existing_references(text):
    match = re.search(r"^# References\s*$", text, flags=re.MULTILINE)
    if not match:
        return text
    return text[:match.start()].rstrip() + "\n"


def process_text(text):
    text = strip_existing_references(text)

    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    id_map = {}
    refs = []

    def replace(match):
        label = match.group(1).strip()
        url = match.group(2).strip()
        if label.isdigit() or url.startswith("#"):
            return match.group(0)
        norm = normalize_url(url)
        if norm not in id_map:
            new_id = len(refs) + 1
            id_map[norm] = new_id
            refs.append({"id": new_id, "label": label or url, "url": url})
        return f"[{id_map[norm]}]({url})"

    new_text = link_re.sub(replace, text)

    if refs:
        ref_lines = ["", "# References", ""]
        for ref in refs:
            ref_lines.append(f"{ref['id']}. [{ref['label']}]({ref['url']})")
        new_text = new_text.rstrip() + "\n" + "\n".join(ref_lines) + "\n"

    return new_text, len(refs)


def process_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content, ref_count = process_text(content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Successfully processed {file_path}")
    print(f"Consolidated into {ref_count} unique references.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_inline_citations.py <file_path>")
        sys.exit(1)
    process_file(sys.argv[1])
