import re
import sys

def parse_references(text):
    """
    Parses the reference section into a list of source objects.
    Reference section is assumed to be a sequence of blocks separated by blank lines.
    Each block contains one or more citations [N](url) and metadata.
    """
    # Split by double newlines to get blocks
    block_strs = re.split(r'\n\s*\n', text.strip())

    sources = []
    next_id = 1

    for block in block_strs:
        if not block.strip():
            continue

        # Extract all citation IDs [N]
        citation_matches = list(re.finditer(r'\[(\d+)\]\((.*?)\)', block))
        original_ids = [int(m.group(1)) for m in citation_matches]

        if not original_ids:
            continue

        # Extract Main URL
        all_links = list(re.finditer(r'\[([^\]]+)\]\((.*?)\)', block))
        main_url = None

        # Filter out links that are citations (where text is digits)
        non_citation_links = []
        for m in all_links:
            text_content = m.group(1)
            if not text_content.isdigit():
                non_citation_links.append(m)

        if non_citation_links:
            # The last non-citation link is likely the main URL
            last_link = non_citation_links[-1]
            main_url = last_link.group(2)
        else:
            # If no distinct main link, use the first citation URL
            if citation_matches:
                main_url = citation_matches[0].group(2)

        # Extract Title
        clean_text = re.sub(r'\[\d+\]\(.*?\)', '', block)
        if non_citation_links:
             # Remove the specific string of the last link
             link_str = non_citation_links[-1].group(0)
             clean_text = clean_text.replace(link_str, '')

        clean_text = clean_text.replace('\n', ' ').strip()
        if not clean_text:
            clean_text = "Reference Title" # Placeholder

        sources.append({
            'new_id': next_id,
            'original_ids': set(original_ids),
            'title': clean_text,
            'url': main_url
        })
        next_id += 1

    return sources

def process_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Identify where References start.
    # Strategy: Find the last header (line starting with #)
    # The reference list should be after the last header.

    last_header_iter = list(re.finditer(r'^#+ .*$', content, re.MULTILINE))
    search_start_pos = 0
    if last_header_iter:
        search_start_pos = last_header_iter[-1].end()

    # Look for the start of the reference list (paragraph starting with [1](...)
    match_start = re.search(r'\n\[1\]\(', content[search_start_pos:])

    if not match_start:
        # Fallback: search from beginning
        match_start = re.search(r'\n\[1\]\(', content)
        if not match_start:
            print("Could not find start of reference list (looking for '\\n[1](').")
            return
        split_index = match_start.start()
    else:
        split_index = search_start_pos + match_start.start()

    body_text = content[:split_index]
    ref_text = content[split_index:]

    # 2. Parse References
    sources = parse_references(ref_text)

    # Map Old ID -> New Source
    id_map = {}
    for source in sources:
        for oid in source['original_ids']:
            id_map[oid] = source

    # 3. Replace in Body
    def replace_citation(match):
        old_id = int(match.group(1))
        url = match.group(2)

        if old_id in id_map:
            new_id = id_map[old_id]['new_id']
            return f"[{new_id}]({url})"
        else:
            return match.group(0)

    new_body = re.sub(r'\[(\d+)\]\((.*?)\)', replace_citation, body_text)

    # 4. Generate New Reference List
    new_ref_list = []

    # Add explicit References header
    new_ref_list.append("# References")
    new_ref_list.append("")

    for source in sources:
        title = source['title'].strip()
        url = source['url'].strip() if source['url'] else ""
        # Format: 1. [Title](url)
        line = f"{source['new_id']}. [{title}]({url})"
        new_ref_list.append(line)

    final_ref_text = "\n".join(new_ref_list)

    final_content = new_body.rstrip() + "\n\n" + final_ref_text + "\n"

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    print(f"Successfully processed {file_path}")
    print(f"Consolidated {len(id_map)} citations into {len(sources)} unique references.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_references.py <file_path>")
    else:
        process_file(sys.argv[1])