from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.store import file_sha256
from roundtable_lab.textio import extract_text, is_supported


class DirectoryEpubTests(unittest.TestCase):
    def test_directory_epub_is_supported_and_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "sample.epub"
            chapter = epub / "OEBPS" / "chapter.xhtml"
            chapter.parent.mkdir(parents=True)
            chapter.write_text(
                "<html><body><h1>标题</h1><p>第一段。</p><p>第二段。</p></body></html>",
                encoding="utf-8",
            )

            self.assertTrue(is_supported(epub))
            text = extract_text(epub)

        self.assertIn("标题", text)
        self.assertIn("第一段。", text)
        self.assertIn("第二段。", text)

    def test_directory_hash_changes_when_inner_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "sample.epub"
            chapter = epub / "OEBPS" / "chapter.xhtml"
            chapter.parent.mkdir(parents=True)
            chapter.write_text("版本一", encoding="utf-8")
            first = file_sha256(epub)

            chapter.write_text("版本二", encoding="utf-8")
            second = file_sha256(epub)

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
