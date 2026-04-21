# Agent Invocation

## Codex

### Option A: use as a local project skill

If the Codex environment can read local project files, tell it to open and follow:

`skills/obsidian-bib-extractor-workflow/SKILL.md`

Example prompt:

```text
Use the local skill at skills/obsidian-bib-extractor-workflow/SKILL.md.
From this repository root, first cd into ./scripts/obsidian-bib-extractor.
Then run the Obsidian Bib Extractor on /path/to/vault,
write references.bib and extraction_report.json, and summarize the results.
```

### Option B: install into `$CODEX_HOME/skills`

Copy or symlink this folder:

```bash
mkdir -p "$CODEX_HOME/skills"
cp -R ./skills/obsidian-bib-extractor-workflow "$CODEX_HOME/skills/"
```

Then a Codex user can invoke it naturally in the prompt, for example:

```text
Use the obsidian-bib-extractor-workflow skill to scan /path/to/vault,
generate references.bib, then preview hyperlink replacement with a dry-run.
```

## Claude Code

Claude Code does not rely on Codex skills metadata, so the simplest pattern is to make it read the skill file directly.

Example prompt:

```text
Read ./skills/obsidian-bib-extractor-workflow/SKILL.md and follow it.
Work from the current repository root, then switch into ./scripts/obsidian-bib-extractor before running commands.
Run a dry-run extraction on /path/to/vault and tell me which output files will be produced.
```

If the Claude Code environment does not automatically load local files, paste the relevant command block from `SKILL.md` into the prompt.

## Recommended prompting pattern

When another agent is driving this toolkit, specify all of the following:

- repository root or working directory
- input Markdown directory
- whether the run is dry-run or write mode
- desired output filenames
- whether Zotero import is in scope

Concrete example:

```text
Use the local Obsidian Bib Extractor skill in ./skills/obsidian-bib-extractor-workflow/SKILL.md.
From this repo root, first enter ./scripts/obsidian-bib-extractor.
Then scan /path/to/obsidian-vault, write references.bib,
write extraction_report.json, and do not modify note files yet.
After that, preview cite replacement with --dry-run.
```
