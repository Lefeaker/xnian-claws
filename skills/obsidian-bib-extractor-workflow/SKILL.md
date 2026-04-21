---
name: obsidian-bib-extractor-workflow
description: Use this skill when working with the Obsidian Bib Extractor toolkit in this repository: extracting DOI/arXiv/PMID/URL references from Markdown, generating BibTeX, replacing hyperlinks with [@citekey], or importing failed URLs into Zotero. This skill should also be used when another agent needs the exact CLI commands, expected inputs/outputs, dry-run workflow, or setup steps for this toolkit.
---

# Obsidian Bib Extractor Workflow

Use this skill from the repository root of `xnian-claws`, then switch into:
`scripts/obsidian-bib-extractor`

That tool directory contains:
`obsidian_bib_extractor.py`, `obsidian_cite_replacer.py`, and `zotero_failed_url_importer.py`.

## When to use

Use this skill when the user wants to:

- scan an Obsidian or Markdown directory and generate a `.bib` file
- preview or apply hyperlink replacement to `[@citekey]`
- retry failed URLs and import them into Zotero
- understand the required environment, cache files, reports, and expected outputs

## Quick setup

If dependencies are not installed yet, run:

```bash
cd scripts/obsidian-bib-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If a virtual environment already exists, activate it before running the Python scripts.

## Main workflows

### 1) Extract references into BibTeX

Run after `cd scripts/obsidian-bib-extractor`:

```bash
python obsidian_bib_extractor.py \
  --input /path/to/markdown-vault \
  --output references.bib \
  --report extraction_report.json \
  --cache cache.sqlite \
  --verbose
```

Notes:

- `--input` is required.
- Output files are created relative to the current working directory unless absolute paths are provided.
- Use `--strategy-config strategy_fast.json` for a stricter, faster pass.
- Use `--strategy-config strategy_full.json` for broader recall.
- Use `--dry-run` if the user only wants candidate extraction without network fetches.

### 2) Replace links with `[@citekey]`

Always recommend a preview first:

```bash
python obsidian_cite_replacer.py \
  --input /path/to/markdown-vault \
  --bib references.bib \
  --report cite_replace_report.json \
  --all-files \
  --dry-run
```

To write changes back:

```bash
python obsidian_cite_replacer.py \
  --input /path/to/markdown-vault \
  --bib references.bib \
  --report cite_replace_report.json \
  --all-files \
  --backup-ext .bak
```

Notes:

- Prefer `--dry-run` before modifying user files.
- Use `--path-contains "Some Folder"` instead of `--all-files` to scope replacements.
- Matching priority is DOI first, then normalized URL variants.

### 3) Import failed URLs into Zotero

Dry-run first:

```bash
python zotero_failed_url_importer.py \
  --report extraction_report.json \
  --cache cache.sqlite \
  --target-collection-name "Imported from Obsidian" \
  --fallback-collection-name "Webpage fallback" \
  --dry-run
```

Apply for real only if Zotero desktop and its local connector API are available:

```bash
python zotero_failed_url_importer.py \
  --report extraction_report.json \
  --cache cache.sqlite \
  --target-collection-name "Imported from Obsidian" \
  --fallback-collection-name "Webpage fallback"
```

Notes:

- The script expects Zotero local API at `http://127.0.0.1:23119`.
- The target collection should already exist.
- If the metadata fetch still fails, the script falls back to a webpage item.

## Outputs and files

- `references.bib`: generated BibTeX library
- `extraction_report.json`: structured extraction/fetch report
- `cite_replace_report.json`: replacement preview or apply report
- `cache.sqlite`: request cache
- `zotero_import_report.json`: Zotero import results

## Agent behavior

When using this toolkit:

1. Confirm the working directory is `scripts/obsidian-bib-extractor`.
2. Prefer preview or dry-run modes before destructive changes.
3. Keep user-specific paths out of commands unless the user explicitly provides them.
4. Mention generated files in the handoff.
5. If the user asks how to invoke the toolkit, use the commands in `references/agent-invocation.md`.

Read `references/agent-invocation.md` when the user explicitly asks how Codex or Claude Code should call this toolkit.
