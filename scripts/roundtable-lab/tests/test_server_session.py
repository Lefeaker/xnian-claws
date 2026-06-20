from __future__ import annotations

import unittest

from roundtable_lab.server import BrowserRoundtableSession, update_session_history
from roundtable_lab.roundtable import AgentResult


class ServerSessionTests(unittest.TestCase):
    def test_update_session_history_preserves_previous_round_for_next_round(self) -> None:
        session = BrowserRoundtableSession(
            session_id="s1",
            topic="主题",
            participants=["汪曾祺"],
        )

        update_session_history(
            session,
            question="第一轮问题",
            results=[AgentResult(person="汪曾祺", evidence=[], speech="第一轮发言")],
            moderator="第一轮主持总结",
        )

        self.assertEqual(session.round_number, 1)
        self.assertIn("第一轮发言", session.history)
        self.assertIn("第一轮主持总结", session.history)

        update_session_history(
            session,
            question="第二轮问题",
            results=[AgentResult(person="汪曾祺", evidence=[], speech="第二轮发言")],
            moderator="第二轮主持总结",
        )

        self.assertEqual(session.round_number, 2)
        self.assertIn("第一轮发言", session.history)
        self.assertIn("第二轮发言", session.history)


if __name__ == "__main__":
    unittest.main()
