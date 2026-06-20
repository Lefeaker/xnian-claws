from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.server import build_material_status


class ServerStatusTests(unittest.TestCase):
    def test_build_material_status_counts_people_sources_and_indexed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "materials" / "汪曾祺" / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "材料.md").write_text("人间草木", encoding="utf-8")

            status = build_material_status(root, {"汪曾祺": 12})

        self.assertEqual(status[0]["person"], "汪曾祺")
        self.assertEqual(status[0]["source_count"], 1)
        self.assertEqual(status[0]["indexed_chunks"], 12)
        self.assertEqual(status[0]["sources"][0]["name"], "材料.md")


if __name__ == "__main__":
    unittest.main()
