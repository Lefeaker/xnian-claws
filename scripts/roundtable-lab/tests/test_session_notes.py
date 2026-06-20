from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.server import load_session_notes, save_session_notes


class SessionNotesTests(unittest.TestCase):
    def test_save_and_load_session_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            save_session_notes(session_dir, "## 我的重点\n\n- 第一条")
            notes = load_session_notes(session_dir)

        self.assertEqual(notes, "## 我的重点\n\n- 第一条")


if __name__ == "__main__":
    unittest.main()
