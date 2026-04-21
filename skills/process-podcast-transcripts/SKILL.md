---
name: process-podcast-transcripts
description: Convert podcast Word transcripts and Xiaoyuzhou show notes into Obsidian-ready Markdown. Use when processing podcast .docx transcripts, AI summary docs, and show notes, especially when the user wants speaker-name replacement, timestamped transcripts, AI notes at the top, show-notes timestamp headings, episode-scoped wiki notes, OCR from show-notes images, ASR correction, and inline Obsidian double links.
---

# Process Podcast Transcripts

## Goal

Produce one complete Obsidian package for a podcast episode:

- YAML frontmatter at the very top of each episode transcript Markdown file with the Xiaoyuzhou episode URL and the processing date.
- `带时间戳/<episode-title>.md` as the canonical processed transcript.
- `<episode-title>.md` derived from the timestamped file by stripping utterance timestamps.
- `## AI纪要` at the top when an AI summary Word document exists.
- `## 正文` before the transcript body.
- Show-notes timestamp titles inserted as `###` headings at matching transcript positions.
- Episode-scoped wiki pages under `wiki/<episode-title>/`.
- Inline wiki double links in the transcript text itself.
- Blank lines between speaker turns in the transcript body.
- Reusable ASR corrections added to `播客转写修正词表.md`.

## Canonical Workspace

Use the user's podcast workspace root. If the user does not specify one, ask for it or infer it from the current project context.

```text
<podcast-workspace>
```

Important paths:

- `convert_podcasts.py`: base DOCX-to-Markdown converter.
- `播客转写修正词表.md`: reusable ASR and terminology correction table.
- `带时间戳/`: canonical timestamp-preserving output.
- `wiki/<episode-title>/`: episode-scoped wiki folder.

Required YAML shape for episode transcript files:

```yaml
---
xiaoyuzhou_url: <episode-url>
processed_date: YYYY-MM-DD
---
```

## One Path Workflow

### 1. Identify Inputs

Use explicit paths when provided. Otherwise:

- Transcript: newest relevant `.docx` in the user's Downloads folder.
- AI summary: matching `AI纪要_*.docx` when present.
- Show notes: prefer the user-provided local Xiaoyuzhou HTML over the live URL.

Never rely only on visible DOM text. Xiaoyuzhou show notes may store glossary cards as base64 images.

### 2. Convert Word Transcript To Timestamped Canonical Markdown

First create or update only the timestamp-preserving transcript:

```text
带时间戳/<episode-title>.md
```

Rules:

- Replace generic speakers with names using self-introductions/show notes.
- If the episode is clearly a single-speaker monologue, omit speaker labels entirely in both the timestamped and non-timestamped transcript bodies.
- Add YAML frontmatter before the H1 in both the timestamped and non-timestamped episode transcript files.
- Preserve every original `- [hh:mm:ss]` utterance timestamp.
- In `## 正文`, insert a blank line between every utterance or paragraph. Treat each speaker turn as its own paragraph even when the same speaker continues.
- Do not strip timestamps yet.
- Correct obvious speaker/name errors immediately, e.g. `梦岩 -> 孟岩`.

### 3. Add AI Summary At The Top

If an AI summary Word document exists:

1. Convert it to Markdown.
2. Insert it at the top of the timestamped file after the H1 title.
3. Use this structure:

```markdown
---
xiaoyuzhou_url: <episode-url>
processed_date: YYYY-MM-DD
---

# <episode-title>

## AI纪要

...structured AI summary...

## 正文

- [00:01:18] ...
```

Render AI summary sections as `###`/`####` headings as needed. Apply ASR corrections and inline wiki links to the AI summary too, not only to the transcript.

### 4. Process Xiaoyuzhou Show Notes

Restrict extraction to:

```css
section[aria-label="节目show notes"]
```

Do not treat comments as show notes.

Extract:

- The `时间戳` section.
- The `猜你想搜` section when present.
- Older-style `本期内容相关资料` / `内容相关资料` sections when `猜你想搜` is absent.
- All links in show notes.
- Every image inside show notes, including `data:image/...;base64,...`.

Xiaoyuzhou has at least two common show-notes layouts:

- Newer layout: `时间戳` + `猜你想搜`
- Older layout: `时间轴` + `本期内容相关资料` + many inline images

Handle both. Do not assume `猜你想搜` exists.

OCR all show-notes images. On macOS, use the Vision framework if Python OCR packages are unavailable.

Image policy:

- Pure text card: OCR it, create wiki text, then remove/do not keep the image.
- Real visual information, such as chart, graph, table-like visual, or structure diagram: copy to `wiki/<episode-title>/assets/...` and embed in the related wiki page.
- Keep only image files actually referenced by wiki pages.

### 5. Create Episode-Scoped Wiki

Always create:

```text
wiki/<episode-title>/
wiki/<episode-title>/assets/
```

For each show-notes concept, create:

```text
wiki/<episode-title>/<concept>.md
```

Include:

- Title.
- Clean explanation text first, immediately after the title.
- Original image after the explanation only when it is a real visual, not a pure text screenshot.
- Source timestamp, source episode backlink, show-notes source URL, and external links last.

Use this order:

```markdown
# <concept>

<clean explanation text>

![optional real visual](assets/<image>)

- 来源时间：<timestamp>
- 来源播客：[[<episode-title>]]
- Show notes：[小宇宙](<episode-url>)
- 外部链接：...
```

Do not put source metadata before the explanation. A reader opening a wiki note should see the concept explanation first.

### 6. Insert Show Notes Timestamp Headings

Use the show notes `时间戳` section as chapter headings.

In `带时间戳/<episode-title>.md`, insert each title before the first utterance whose timestamp is equal to or later than the show-notes timestamp:

```markdown
### [58:59] 期权不是保险，期权是它标的物波动的凝结

- [00:58:59] ...
```

These headings are not utterance timestamps. Do not alter the original utterance timestamps.

### 7. Apply ASR Corrections And Inline Links To Timestamped File

Use `播客转写修正词表.md` first. Add new reusable corrections there.

Rules:

- Apply corrections to the AI summary and transcript body.
- Preserve diacritics for Pali/Sanskrit terms, such as `Anattā`, `Avijjā`, `Saṅkhāra`, `Vipassanā`, `Mahāsatipaṭṭhāna Sutta`, `Ānāpāna`, `Phassa`, `Karma`.
- Avoid blind global linking for single-character terms like `苦`、`空`、`触`、`止`、`业`; link only clear technical contexts or longer phrases.
- Use inline links:

```markdown
如果大家对[[wiki/<episode-title>/塔勒布的期权定价模型以及嘉宾的拆解|塔勒布的期权定价模型]]感兴趣...
```

Do not add a wiki dump at the top and do not insert block embeds next to transcript lines.

### 8. Derive The Main Markdown From Timestamped Markdown

Only after the timestamped file is complete:

1. Copy `带时间戳/<episode-title>.md` to `<episode-title>.md`.
2. Strip utterance timestamps: `- [hh:mm:ss] 说话人：... -> 说话人：...`.
3. Convert show-notes headings: `### [mm:ss] title -> ### title`.
4. Preserve blank lines between every utterance or paragraph in the transcript body.
5. Do not collapse consecutive same-speaker utterances into one dense block unless the user explicitly asks for that.
6. Keep `## AI纪要` and `## 正文` unchanged.

This avoids doing all corrections twice.

### 9. Validate

Run checks like:

```bash
rg -n '梦岩|塔罗布|休默|休莫|巴黎语|sankara|雅特|尼亚|入席|出席|\\[\\[[^\\]\\n]*\\[\\[' <main.md> <timestamped.md>
rg --pcre2 -n '\\[\\[wiki/(?!<episode-title>/)' <main.md> <timestamped.md> 'wiki/<episode-title>'
rg -n '^## AI纪要|^## 正文|^### ' <main.md> <timestamped.md>
find 'wiki/<episode-title>/assets' -type f
find wiki -maxdepth 1 -type f
```

Confirm:

- Both episode transcript files start with YAML frontmatter containing `xiaoyuzhou_url` and `processed_date`.
- AI notes are present before `## 正文`.
- Both files contain the show-notes timestamp titles as `###` headings at corresponding transcript positions.
- Timestamped file still has all `- [hh:mm:ss]` utterance markers.
- Main file has no utterance timestamp prefixes.
- In both transcript bodies, every utterance or paragraph is separated by a blank line.
- Wiki links are episode-scoped.
- Each wiki note starts with title then clean explanation; source metadata and external links are at the bottom.
- No episode wiki files remain loose in `wiki/` root.
- Pure text images are removed; only true visual assets are kept.

## Common Pitfalls

- Show-notes glossary content may be in images, not text.
- Xiaoyuzhou comments appear after show notes and can look like show notes when reading full rendered text.
- Over-linking single Chinese characters creates false links, especially `空` in `做空` or `大空头`.
- Re-processing main and timestamped files separately causes drift; process timestamped first, then derive main.
