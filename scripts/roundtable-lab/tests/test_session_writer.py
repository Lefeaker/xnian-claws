from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from roundtable_lab.roundtable import AgentResult, write_session


class SessionWriterTests(unittest.TestCase):
    def test_write_session_keeps_each_round_in_its_own_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"

            write_session(
                session_dir=session_dir,
                topic="主题",
                question="第一轮问题",
                results=[AgentResult(person="甲", evidence=[], speech="第一轮发言", audit="第一轮稽核")],
                moderator="第一轮主持",
                round_number=1,
            )
            write_session(
                session_dir=session_dir,
                topic="主题",
                question="第二轮问题",
                results=[AgentResult(person="甲", evidence=[], speech="第二轮发言", audit="第二轮稽核")],
                moderator="第二轮主持",
                round_number=2,
            )

            round_01 = session_dir / "round-01"
            round_02 = session_dir / "round-02"

            self.assertTrue((round_01 / "agents.md").exists())
            self.assertTrue((round_02 / "agents.md").exists())
            self.assertIn("第一轮发言", (round_01 / "agents.md").read_text(encoding="utf-8"))
            self.assertIn("第二轮发言", (round_02 / "agents.md").read_text(encoding="utf-8"))
            self.assertIn("第二轮问题", (session_dir / "rounds.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
