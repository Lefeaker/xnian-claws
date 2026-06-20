from __future__ import annotations

import unittest

from roundtable_lab.roundtable import (
    build_agent_messages,
    build_conclusion_messages,
    build_deepen_question,
    build_opening_question,
    build_speaker_selection_messages,
    parse_speaker_selection,
)


class LjgRoundtableRuleTests(unittest.TestCase):
    def test_opening_question_is_definition_question(self) -> None:
        question = build_opening_question("汪曾祺笔下人物的浑圆状态")

        self.assertIn("如何定义", question)
        self.assertIn("核心要素", question)
        self.assertIn("汪曾祺笔下人物的浑圆状态", question)

    def test_agent_prompt_requires_action_label_and_brief_summary(self) -> None:
        messages = build_agent_messages(
            person="汪曾祺",
            persona="日常生活",
            topic="浑圆状态",
            question="如何定义浑圆？",
            history="【沈从文】地方性很重要。",
            evidence=[],
        )
        text = "\n".join(message["content"] for message in messages)

        self.assertIn("【汪曾祺】【陈述/质疑/补充/反驳/修正/综合】", text)
        self.assertIn("**简言之**：", text)
        self.assertIn("必须回应前文", text)

    def test_parse_speaker_selection_accepts_json_and_falls_back_to_name_match(self) -> None:
        self.assertEqual(
            parse_speaker_selection('{"speaker":"项飙","stop_round":false}', ["汪曾祺", "项飙"]),
            ("项飙", False),
        )
        self.assertEqual(
            parse_speaker_selection("下一位请韩炳哲回应", ["韩炳哲", "庄子"]),
            ("韩炳哲", False),
        )
        self.assertEqual(
            parse_speaker_selection('{"speaker":"","stop_round":true}', ["韩炳哲"]),
            ("", True),
        )

    def test_speaker_selection_prompt_contains_candidates_and_transcript(self) -> None:
        messages = build_speaker_selection_messages(
            topic="浑圆状态",
            question="如何定义？",
            prior_history="上一轮总结",
            current_transcript="【汪曾祺】发言",
            candidates=["沈从文", "项飙"],
        )
        text = "\n".join(message["content"] for message in messages)

        self.assertIn("候选发言者", text)
        self.assertIn("沈从文", text)
        self.assertIn("上一轮总结", text)
        self.assertIn("JSON", text)

    def test_deepen_question_uses_last_moderator_summary(self) -> None:
        question = build_deepen_question("原议题", "【本轮核心争议点】附近是否会被消费化？")

        self.assertIn("深入", question)
        self.assertIn("附近是否会被消费化", question)

    def test_conclusion_prompt_requests_knowledge_network_and_open_questions(self) -> None:
        messages = build_conclusion_messages(topic="浑圆状态", history="多轮记录")
        text = "\n".join(message["content"] for message in messages)

        self.assertIn("完整知识网络", text)
        self.assertIn("开放问题", text)


if __name__ == "__main__":
    unittest.main()
