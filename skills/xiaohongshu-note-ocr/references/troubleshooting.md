# Troubleshooting

## Short Link Resolves But `__INITIAL_STATE__` Is Missing

Try the full resolved URL in a browser session. Xiaohongshu occasionally serves a different shell page depending on cookies, user agent, region, or bot checks. If browser access shows the note but source parsing fails, capture the network response or page state instead of guessing endpoints.

## Image URLs Time Out

Retry with the alternate scheme. Xiaohongshu CDN URLs sometimes fail TLS handshakes on `https://` but succeed on `http://`, or vice versa. The downloader already tries both.

## Image Count Does Not Match User Claim

Trust the manifest extracted from the page unless the user gave a stronger source. Report both numbers explicitly: “manifest has 18 images; user expected 19.” Do not fabricate missing pages.

## OCR Confuses Chinese Glyphs

Common issues:
- stylized titles: `论` misread as `訟`
- traditional or variant glyphs: `眞`, `會`, `悅`
- page-boundary fragments: missing `为`, `因`, or `为什么`
- punctuation: Chinese quotes and em dashes lost or normalized

Use the original images for manual correction when producing a proofread draft.

## Vision OCR Is Unavailable

Confirm the system has Swift and Vision:

```bash
swift --version
swift -e 'import Vision; print("Vision OK")'
```

If Vision is unavailable, inspect local OCR options before installing anything:

```bash
command -v tesseract || true
python3 - <<'PY'
import importlib.util
for name in ["PIL", "pytesseract", "easyocr"]:
    print(name, bool(importlib.util.find_spec(name)))
PY
```
