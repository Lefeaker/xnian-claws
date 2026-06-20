from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.config import load_settings


class EmbeddingDimensionConfigTests(unittest.TestCase):
    def test_load_settings_reads_embed_dimensions_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                "\n".join(
                    [
                        'embed_model = "Qwen/Qwen3-Embedding-8B"',
                        "embed_dimensions = 4096",
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_settings(config)

        self.assertEqual(settings.embed_model, "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(settings.embed_dimensions, 4096)


if __name__ == "__main__":
    unittest.main()
