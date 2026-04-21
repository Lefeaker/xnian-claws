#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def assert_file(path: Path) -> None:
    assert path.exists(), f"missing {path.relative_to(ROOT)}"
    assert path.stat().st_size > 0, f"empty {path.relative_to(ROOT)}"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def find_quick_validator() -> Path | None:
    candidates = []
    if os.environ.get("SKILL_VALIDATOR"):
        candidates.append(Path(os.environ["SKILL_VALIDATOR"]))
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    candidates.extend(
        [
            codex_home / "skills/.system/skill-creator/scripts/quick_validate.py",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def assert_minimal_frontmatter() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    frontmatter = text.split("---", 2)[1]
    assert "\nname:" in f"\n{frontmatter}", "frontmatter must include name"
    assert "\ndescription:" in f"\n{frontmatter}", "frontmatter must include description"


def main() -> int:
    assert_file(ROOT / "SKILL.md")
    for rel in [
        "scripts/resolve_note.py",
        "scripts/download_images.py",
        "scripts/make_markdown.py",
        "scripts/ocr_images.swift",
        "references/troubleshooting.md",
        "evals/evals.json",
    ]:
        assert_file(ROOT / rel)

    quick_validate = find_quick_validator()
    if quick_validate:
        result = subprocess.run(
            [sys.executable, str(quick_validate), str(ROOT)],
            text=True,
            capture_output=True,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 and "No module named 'yaml'" in output:
            assert_minimal_frontmatter()
        else:
            assert result.returncode == 0, output
    else:
        assert_minimal_frontmatter()

    make_markdown = load_module(ROOT / "scripts/make_markdown.py")
    sample = """## 图 01

```text
訟盈余：和爱人
一起，能够看到
更大的世界吗？
```

## 图 02

```text
我在很长一段时间内无法这个现象找到一个
令人满意的解释。
```
"""
    cleaned = make_markdown.clean_ocr_markdown(sample, title="论盈余：和爱人一起，能够看到更大的世界吗？")
    assert "## 图" not in cleaned
    assert "訟盈余" not in cleaned
    assert "论盈余：和爱人一起，能够看到更大的世界吗？" in cleaned
    assert "无法为这个现象找到" in cleaned
    assert "\ufffd" not in cleaned

    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        (temp / "manifest.json").write_text(
            '{"title":"测试标题","source_url":"https://xhslink.com/example","note_url":"https://www.xiaohongshu.com/explore/abc","images":[{"index":1,"path":"image_01.jpg"}]}',
            encoding="utf-8",
        )
        (temp / "image_01.jpg").write_bytes(b"fake")
        verify = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/make_markdown.py"),
                "verify",
                "--work-dir",
                str(temp),
            ],
            text=True,
            capture_output=True,
        )
        assert verify.returncode == 0, verify.stdout + verify.stderr

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
