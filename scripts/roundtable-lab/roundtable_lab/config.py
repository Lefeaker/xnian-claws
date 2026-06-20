from __future__ import annotations

import os
import json
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_profile: str = "direct"
    base_url: str = "https://api.siliconflow.cn/v1"
    chat_base_url: str | None = None
    embed_base_url: str | None = None
    chat_model: str = "Qwen/Qwen3-30B-A3B"
    embed_model: str = "BAAI/bge-m3"
    chat_wire_api: str = "chat_completions"
    concurrency: int = 5
    max_retries: int = 2
    embed_batch_size: int = 32
    embed_dimensions: int | None = None
    chunk_size: int = 1200
    chunk_overlap: int = 180
    top_k: int = 8
    temperature: float = 0.35
    max_tokens: int = 1800
    api_key: str | None = None
    chat_api_key: str | None = None
    embed_api_key: str | None = None
    cc_switch_db: str = "~/.cc-switch/cc-switch.db"
    cc_switch_codex_provider: str | None = None
    chat_provider_name: str = "direct"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _read_cc_switch_current_codex(db_path: Path, provider_id: str | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        selected_provider_id = provider_id
        if not selected_provider_id:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'currentProviderCodex'"
            ).fetchone()
            selected_provider_id = str(row["value"]) if row else None

        if selected_provider_id:
            row = conn.execute(
                """
                SELECT id, name, settings_config
                FROM providers
                WHERE app_type = 'codex' AND id = ?
                """,
                (selected_provider_id,),
            ).fetchone()
        else:
            row = None

        if row is None:
            row = conn.execute(
                """
                SELECT id, name, settings_config
                FROM providers
                WHERE app_type = 'codex' AND is_current = 1
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            raise ValueError(f"No current codex provider found in {db_path}")

        settings_config = json.loads(row["settings_config"])
        codex_config = tomllib.loads(settings_config.get("config", ""))
        model = codex_config.get("model")
        provider_name = codex_config.get("model_provider")
        model_providers = codex_config.get("model_providers", {})
        provider_config = model_providers.get(provider_name, {}) if provider_name else {}

        auth = settings_config.get("auth", {})
        api_key = auth.get("OPENAI_API_KEY") if isinstance(auth, dict) else None
        base_url = provider_config.get("base_url")
        wire_api = provider_config.get("wire_api", "responses")

        if not api_key:
            raise ValueError(f"Current codex provider {row['name']} has no OPENAI_API_KEY")
        if not model:
            raise ValueError(f"Current codex provider {row['name']} has no model")
        if not base_url:
            raise ValueError(f"Current codex provider {row['name']} has no base_url")

        return {
            "chat_provider_name": str(row["name"]),
            "chat_api_key": api_key,
            "chat_base_url": base_url,
            "chat_model": model,
            "chat_wire_api": wire_api,
        }
    finally:
        conn.close()


def load_settings(config_path: Path | None = None) -> Settings:
    resolved_config_path = config_path or PROJECT_ROOT / "config.toml"
    load_env_file(resolved_config_path.parent / ".env")
    data = _read_toml(resolved_config_path)

    values: dict[str, Any] = {field: getattr(Settings(), field) for field in Settings.__dataclass_fields__}
    values.update(data)

    env_map = {
        "api_key": "SILICONFLOW_API_KEY",
        "base_url": "SILICONFLOW_BASE_URL",
        "chat_model": "ROUNDTABLE_CHAT_MODEL",
        "embed_model": "SILICONFLOW_EMBED_MODEL",
        "chat_base_url": "ROUNDTABLE_CHAT_BASE_URL",
        "embed_base_url": "ROUNDTABLE_EMBED_BASE_URL",
        "chat_api_key": "ROUNDTABLE_CHAT_API_KEY",
        "embed_api_key": "ROUNDTABLE_EMBED_API_KEY",
        "chat_wire_api": "ROUNDTABLE_CHAT_WIRE_API",
        "embed_dimensions": "SILICONFLOW_EMBED_DIMENSIONS",
    }
    for field, env_name in env_map.items():
        if os.getenv(env_name):
            values[field] = int(os.getenv(env_name)) if field == "embed_dimensions" else os.getenv(env_name)

    if values.get("api_profile") == "cc-switch-codex":
        values.update(
            _read_cc_switch_current_codex(
                Path(str(values["cc_switch_db"])).expanduser(),
                values.get("cc_switch_codex_provider"),
            )
        )

    explicit_chat_base_url = bool(values.get("chat_base_url"))

    if not values.get("chat_base_url"):
        values["chat_base_url"] = values.get("base_url")
    if not values.get("embed_base_url"):
        values["embed_base_url"] = values.get("base_url")
    if not values.get("chat_api_key") and not explicit_chat_base_url:
        values["chat_api_key"] = values.get("api_key")
    if not values.get("embed_api_key"):
        values["embed_api_key"] = values.get("api_key")

    return Settings(**values)
