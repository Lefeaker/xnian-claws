from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.server import (
    BrowserRoundtableSession,
    load_browser_session,
    parse_saved_rounds,
    list_saved_sessions,
    save_browser_session_metadata,
)


class SessionRestoreTests(unittest.TestCase):
    def test_save_and_load_browser_session_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "20260422T000000-topic"
            session = BrowserRoundtableSession(
                session_id="abc123",
                topic="主题",
                participants=["汪曾祺", "项飙"],
                history="## 第 1 轮\n内容",
                round_number=1,
                session_dir=session_dir,
                last_question="第一轮问题",
                last_moderator="主持总结",
            )

            save_browser_session_metadata(session)
            loaded = load_browser_session(session_dir)

        self.assertEqual(loaded.session_id, "abc123")
        self.assertEqual(loaded.topic, "主题")
        self.assertEqual(loaded.participants, ["汪曾祺", "项飙"])
        self.assertEqual(loaded.round_number, 1)
        self.assertIn("第 1 轮", loaded.history)

    def test_list_saved_sessions_returns_recent_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = BrowserRoundtableSession(
                session_id="old",
                topic="旧主题",
                participants=["汪曾祺"],
                round_number=1,
                session_dir=root / "20260421T000000-old",
            )
            newer = BrowserRoundtableSession(
                session_id="new",
                topic="新主题",
                participants=["项飙"],
                round_number=2,
                session_dir=root / "20260422T000000-new",
            )
            save_browser_session_metadata(older)
            save_browser_session_metadata(newer)

            sessions = list_saved_sessions(root, limit=2)

        self.assertEqual([item["session_id"] for item in sessions], ["new", "old"])
        self.assertEqual(sessions[0]["round_number"], 2)

    def test_parse_saved_rounds_reads_agents_audit_and_moderator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            round_dir = session_dir / "round-01"
            round_dir.mkdir(parents=True)
            (round_dir / "question.md").write_text("# 第 1 轮问题\n\n什么是浑圆？\n", encoding="utf-8")
            (round_dir / "agents.md").write_text(
                "# 汪曾祺\n\n第一位发言\n\n---\n\n# 项飙\n\n第二位发言\n",
                encoding="utf-8",
            )
            (round_dir / "audit.md").write_text(
                "# 汪曾祺\n\n第一位稽核\n\n---\n\n# 项飙\n\n第二位稽核\n",
                encoding="utf-8",
            )
            (round_dir / "moderator.md").write_text("主持人总结", encoding="utf-8")

            rounds = parse_saved_rounds(session_dir)

        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["question"], "什么是浑圆？")
        self.assertEqual(rounds[0]["agents"][0]["person"], "汪曾祺")
        self.assertEqual(rounds[0]["agents"][0]["audit"], "第一位稽核")
        self.assertEqual(rounds[0]["moderator"], "主持人总结")


if __name__ == "__main__":
    unittest.main()
