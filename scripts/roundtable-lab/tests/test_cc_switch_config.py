from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from roundtable_lab.config import load_settings
from roundtable_lab.siliconflow import extract_response_text


def create_cc_switch_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """
        CREATE TABLE providers (
            id TEXT NOT NULL,
            app_type TEXT NOT NULL,
            name TEXT NOT NULL,
            settings_config TEXT NOT NULL,
            is_current BOOLEAN NOT NULL DEFAULT 0,
            PRIMARY KEY (id, app_type)
        )
        """
    )
    conn.execute("INSERT INTO settings(key, value) VALUES ('currentProviderCodex', 'codex-xychat')")
    settings_config = {
        "auth": {"OPENAI_API_KEY": "test-key"},
        "config": "\n".join(
            [
                'model_provider = "xychat"',
                'model = "gpt-5.4"',
                "",
                "[model_providers.xychat]",
                'base_url = "https://xychat.example.com/codex/v1"',
                'wire_api = "responses"',
            ]
        ),
    }
    conn.execute(
        """
        INSERT INTO providers(id, app_type, name, settings_config, is_current)
        VALUES (?, 'codex', 'xychat', ?, 1)
        """,
        ("codex-xychat", json.dumps(settings_config)),
    )
    conn.commit()
    conn.close()


class CcSwitchConfigTests(unittest.TestCase):
    def test_load_settings_uses_cc_switch_codex_for_chat_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "cc-switch.db"
            create_cc_switch_db(db_path)
            config_path = root / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        'api_profile = "cc-switch-codex"',
                        f'cc_switch_db = "{db_path}"',
                        'embed_base_url = "https://api.siliconflow.cn/v1"',
                        'embed_api_key = "embed-key"',
                        'embed_model = "BAAI/bge-m3"',
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertEqual(settings.chat_base_url, "https://xychat.example.com/codex/v1")
        self.assertEqual(settings.chat_api_key, "test-key")
        self.assertEqual(settings.chat_model, "gpt-5.4")
        self.assertEqual(settings.chat_wire_api, "responses")
        self.assertEqual(settings.embed_base_url, "https://api.siliconflow.cn/v1")
        self.assertEqual(settings.embed_api_key, "embed-key")

    def test_extract_response_text_handles_output_text_and_nested_content(self) -> None:
        class WithOutputText:
            output_text = "直接文本"

        self.assertEqual(extract_response_text(WithOutputText()), "直接文本")

        nested = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "嵌套文本"},
                    ]
                }
            ]
        }

        self.assertEqual(extract_response_text(nested), "嵌套文本")

    def test_custom_chat_base_url_does_not_fallback_to_siliconflow_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        'base_url = "https://api.siliconflow.cn/v1"',
                        'api_key = "siliconflow-key"',
                        'chat_base_url = "https://chat.example.com/codex"',
                        'chat_wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertEqual(settings.embed_api_key, "siliconflow-key")
        self.assertIsNone(settings.chat_api_key)


if __name__ == "__main__":
    unittest.main()
