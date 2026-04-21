---
name: xiaohongshu-note-ocr
description: Use when a user gives a Xiaohongshu or xhslink note URL and asks to OCR image text, extract text from multi-image notes, copy note image text, create Markdown, or produce a manually proofread continuous draft from Xiaohongshu screenshots.
metadata:
  compatibility: macOS with Python 3 and Swift Vision OCR; network access required for Xiaohongshu image download.
---

# Xiaohongshu Note OCR

## Overview

Extract text from Xiaohongshu multi-image notes and turn it into useful Markdown. Keep the workflow narrow: resolve one note, download its note images, OCR them in order, then produce either a raw OCR file or a manually proofread continuous draft.

## When To Use

Use this skill for:
- `xhslink.com` short links or `xiaohongshu.com` note links.
- Requests such as “OCR 出来”, “识别图片文字”, “把小红书图片文字整理成 Markdown”, “人工校对稿”.
- Multi-image text notes where the text is embedded in images.

Do not use this skill for:
- Video-only notes.
- Comments, profiles, feeds, or recommendation scraping.
- Generic OCR jobs unrelated to Xiaohongshu.

## Output Contract

Default output root: `~/download/`.

For each note, create a stable work directory named from the note id:

```text
~/download/xhs_<note_id>/
```

The normal deliverables are:
- `manifest.json`: title, source URL, resolved note URL, image count, and image paths.
- `image_01.jpg`, `image_02.jpg`, ...: original downloaded note images.
- `<title>_OCR.md`: raw OCR Markdown with one section per image.
- `<title>_人工校对稿.md`: continuous proofread Markdown, no page markers, no image section headings.

If the user only asks for OCR, the raw OCR file is enough. If the user asks for “人工校对”, “校对稿”, “修正换行”, “不要分页”, or similar wording, produce the continuous proofread file too.

## Workflow

### 1. Resolve The Note

Run from this skill directory, or replace `scripts/...` with the absolute path to these bundled scripts:

```bash
python3 scripts/resolve_note.py \
  '<xhs-or-xhslink-url>' \
  --download-root "$HOME/download"
```

This writes `manifest.json` and prints the work directory. Prefer this source parsing path before trying a browser session.

If resolving fails, do not create an empty final Markdown. Report the blocker and preserve any debug output.

### 2. Download Images

Run:

```bash
python3 scripts/download_images.py \
  --manifest "$WORK_DIR/manifest.json"
```

The downloader retries, skips already-downloaded files, and falls back between HTTPS and HTTP for CDN edge cases.

If some images fail, report the missing image indexes. Do not claim the OCR is complete.

### 3. Raw OCR

Run:

```bash
swift scripts/ocr_images.swift \
  --manifest "$WORK_DIR/manifest.json" \
  --output "$WORK_DIR/<safe-title>_OCR.md"
```

The Swift script uses macOS Vision. If Vision is unavailable, fall back to another local OCR engine only after checking what is installed.

### 4. Continuous Proofread Draft

For a first automated cleanup, run:

```bash
python3 scripts/make_markdown.py clean \
  --ocr "$WORK_DIR/<safe-title>_OCR.md" \
  --output "$HOME/download/<safe-title>_人工校对稿.md" \
  --title "<note-title>"
```

Then manually review against the raw OCR and original images. This matters because image OCR commonly confuses Chinese title glyphs, punctuation, proper names, and page-boundary sentences.

Manual proofreading should:
- Remove all `## 图 NN` page markers and fenced raw OCR blocks.
- Merge lines broken by image layout.
- Join sentences that continue across image boundaries.
- Preserve meaningful paragraph breaks and list entries.
- Fix obvious OCR errors using the original image when uncertain.
- Keep source attribution near the top if useful to the user.

Do not represent a rule-cleaned draft as “人工校对稿” unless you actually reviewed likely OCR mistakes against source material.

### 5. Verify Before Completion

Run:

```bash
python3 scripts/make_markdown.py verify \
  --work-dir "$WORK_DIR"
```

Also check final files in `~/download/` when the clean copy is written outside the work directory.

Minimum completion evidence:
- Downloaded image count matches `manifest.json`.
- Raw OCR section count matches image count.
- Proofread draft has no `## 图` page markers.
- Proofread draft has no Unicode replacement character `�`.

## Failure Handling

Link cannot resolve:
- Stop and report the exact failing step.
- Do not invent note data.

Page opens but images are absent:
- Save the resolved URL and error.
- Try the browser only if page source parsing fails and the user context suggests the note should be public.

Partial image download:
- Keep downloaded images and manifest.
- Report failed indexes and leave a resumable work directory.

OCR quality is poor:
- Keep the raw OCR file.
- Use original images for manual correction, especially headings, proper nouns, punctuation, and page-boundary text.

## Script Reference

The bundled scripts are intentionally small and composable:
- `scripts/resolve_note.py`: resolve URL and create manifest.
- `scripts/download_images.py`: download images from manifest.
- `scripts/ocr_images.swift`: run macOS Vision OCR into raw Markdown.
- `scripts/make_markdown.py`: clean raw OCR and verify outputs.
- `references/troubleshooting.md`: common Xiaohongshu and Vision OCR failure modes.
