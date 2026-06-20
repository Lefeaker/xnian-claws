from __future__ import annotations

import unittest

from roundtable_lab.server import BrowserRoundtableSession, apply_roundtable_command


class RoundtableCommandTests(unittest.TestCase):
    def test_first_round_defaults_to_opening_definition(self) -> None:
        session = BrowserRoundtableSession(
            session_id="s1",
            topic="汪曾祺笔下人物的浑圆状态",
            participants=["汪曾祺"],
        )

        question, action = apply_roundtable_command(
            session,
            command="可",
            provided_question="",
            new_participant="",
        )

        self.assertEqual(action, "round")
        self.assertIn("如何定义", question)

    def test_deepen_uses_last_moderator_summary(self) -> None:
        session = BrowserRoundtableSession(
            session_id="s1",
            topic="主题",
            participants=["汪曾祺"],
            last_moderator="【本轮核心争议点】附近是否被消费化？",
            last_question="上一轮问题",
        )

        question, action = apply_roundtable_command(
            session,
            command="深入此节",
            provided_question="",
            new_participant="",
        )

        self.assertEqual(action, "round")
        self.assertIn("深入", question)
        self.assertIn("附近是否被消费化", question)

    def test_add_new_participant_appends_once_and_creates_intro_question(self) -> None:
        session = BrowserRoundtableSession(
            session_id="s1",
            topic="主题",
            participants=["汪曾祺"],
            last_question="上一轮问题",
        )

        question, action = apply_roundtable_command(
            session,
            command="引入新人物",
            provided_question="",
            new_participant="项飙",
        )
        apply_roundtable_command(
            session,
            command="引入新人物",
            provided_question="",
            new_participant="项飙",
        )

        self.assertEqual(action, "round")
        self.assertEqual(session.participants.count("项飙"), 1)
        self.assertIn("项飙", question)

    def test_stop_command_returns_conclusion_action(self) -> None:
        session = BrowserRoundtableSession(
            session_id="s1",
            topic="主题",
            participants=["汪曾祺"],
        )

        question, action = apply_roundtable_command(
            session,
            command="止",
            provided_question="",
            new_participant="",
        )

        self.assertEqual(question, "")
        self.assertEqual(action, "conclude")


if __name__ == "__main__":
    unittest.main()
