from __future__ import annotations

import unittest

from roundtable_lab.roundtable import (
    AgentResult,
    append_round_to_history,
    build_agent_messages,
    build_turn_history,
)


class DialogueHistoryTests(unittest.TestCase):
    def test_turn_history_includes_prior_round_and_current_round_previous_speakers(self) -> None:
        prior = append_round_to_history(
            "",
            round_number=1,
            question="第一轮问题",
            results=[AgentResult(person="汪曾祺", evidence=[], speech="第一轮汪曾祺发言")],
            moderator="第一轮主持人总结",
        )

        history = build_turn_history(
            prior_history=prior,
            question="第二轮问题",
            current_results=[AgentResult(person="项飙", evidence=[], speech="第二轮项飙发言")],
        )

        self.assertIn("第一轮汪曾祺发言", history)
        self.assertIn("第一轮主持人总结", history)
        self.assertIn("第二轮问题", history)
        self.assertIn("第二轮项飙发言", history)

    def test_agent_prompt_requires_response_to_previous_speakers_when_history_exists(self) -> None:
        messages = build_agent_messages(
            person="韩炳哲",
            persona="绩效社会",
            topic="现代人的浑圆",
            question="第二轮问题",
            history="【项飙】附近不是景观。",
            evidence=[],
        )

        combined = "\n".join(message["content"] for message in messages)

        self.assertIn("前文已有讨论", combined)
        self.assertIn("必须回应前文", combined)
        self.assertIn("【项飙】附近不是景观。", combined)


if __name__ == "__main__":
    unittest.main()
