from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT, load_settings
from .siliconflow import SiliconFlow
from .store import ChunkHit, CorpusStore


@dataclass(frozen=True)
class AgentResult:
    person: str
    evidence: list[ChunkHit]
    speech: str
    audit: str | None = None


@dataclass(frozen=True)
class RoundResult:
    round_number: int
    question: str
    results: list[AgentResult]
    moderator: str
    history: str


def slugify(text: str, limit: int = 42) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text).strip("-")
    return slug[:limit] or "roundtable"


def read_persona(root: Path, person: str) -> str:
    path = root / "personas" / f"{person}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# {person}\n\n你只能基于检索材料发言；材料不足时必须明确说不足。"


ACTION_LABELS = "陈述/质疑/补充/反驳/修正/综合"


def build_opening_question(topic: str) -> str:
    return f"在深入探讨之前，我们应当如何定义「{topic}」？它的核心要素是什么？"


def format_evidence(evidence: list[ChunkHit]) -> str:
    blocks = []
    for hit in evidence:
        blocks.append(
            "\n".join(
                [
                    f"[{hit.person}:{hit.chunk_id}] score={hit.score:.4f}",
                    f"source={hit.path}#chunk-{hit.chunk_index}",
                    hit.text,
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def format_agent_transcript(result: AgentResult) -> str:
    return f"【{result.person}】\n{result.speech}".strip()


def build_turn_history(
    *,
    prior_history: str,
    question: str,
    current_results: list[AgentResult],
) -> str:
    sections: list[str] = []
    if prior_history.strip():
        sections.append("【前面轮次完整记录】\n" + prior_history.strip())
    sections.append("【本轮问题】\n" + question.strip())
    if current_results:
        current = "\n\n".join(format_agent_transcript(result) for result in current_results)
        sections.append("【本轮已经发生的发言】\n" + current)
    return "\n\n".join(sections)


def append_round_to_history(
    prior_history: str,
    *,
    round_number: int,
    question: str,
    results: list[AgentResult],
    moderator: str,
) -> str:
    body = "\n\n".join(format_agent_transcript(result) for result in results)
    round_text = "\n\n".join(
        [
            f"## 第 {round_number} 轮",
            f"【本轮问题】\n{question}",
            "【人物发言】",
            body,
            "【主持人综述】",
            moderator,
        ]
    )
    return "\n\n".join(part for part in [prior_history.strip(), round_text.strip()] if part)


def build_agent_messages(
    *,
    person: str,
    persona: str,
    topic: str,
    question: str,
    history: str,
    evidence: list[ChunkHit],
) -> list[dict[str, str]]:
    evidence_text = format_evidence(evidence)
    system = f"""你是高保真圆桌中的「{person}」代理。

你的任务不是 cosplay，而是基于「{person}」自己的材料库参与讨论。

硬性规则：
1. 只能依据给定【材料片段】发言。
2. 可以合理化用，但必须标明推演边界。
3. 材料不足时，不许编造；直接说材料不足。
4. 不要使用不属于此人物的问题意识和术语，除非明确标为跨域推演。
5. 必须使用行动标签，第一行格式必须是：
【{person}】【陈述/质疑/补充/反驳/修正/综合】：你的核心发言

6. 每段发言末尾必须有一行：
**简言之**：一句话压缩你的判断

7. 输出必须包含以下证据结构：

【依据材料】
【引用/化用位置】
【推演边界】
【可能越界点】

人物设定与边界：
{persona}
"""
    user = f"""圆桌主题：
{topic}

本轮问题：
{question}

既有讨论：
{history or "暂无。"}

【材料片段】
{evidence_text or "没有检索到材料。"}

请以「{person}」的思想边界作答。"""
    if history.strip():
        user += "\n\n前文已有讨论。你必须回应前文中最值得推进、质疑或修正的一点，不能只自说自话。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_audit_messages(*, person: str, speech: str, evidence: list[ChunkHit]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是高保真圆桌的稽核员，只检查材料忠实度，不替角色发挥。",
        },
        {
            "role": "user",
            "content": f"""请检查「{person}」的发言是否被材料支持。

输出：
【可证部分】
【合理化用】
【疑似越界】
【需要补材料】

材料：
{format_evidence(evidence)}

发言：
{speech}
""",
        },
    ]


def build_moderator_messages(*, topic: str, question: str, results: list[AgentResult]) -> list[dict[str, str]]:
    transcript = "\n\n".join(f"## {result.person}\n{result.speech}" for result in results)
    audits = "\n\n".join(
        f"## {result.person}\n{result.audit}" for result in results if result.audit
    )
    return [
        {
            "role": "system",
            "content": """你是李继刚圆桌方法中的主持人：理性、冷静、求真。
你不替人物发明立场，只组织他们的材料化发言，提炼最深争议点，并画 ASCII 结构图。""",
        },
        {
            "role": "user",
            "content": f"""主题：
{topic}

本轮问题：
{question}

人物发言：
{transcript}

稽核信息：
{audits or "未启用稽核。"}

请输出：
【本轮核心争议点】
【ASCII 思考框架图】
【下一层引导问题】
【指令菜单】可 / 止 / 深入此节 / 引入新人物
""",
        },
    ]


def build_speaker_selection_messages(
    *,
    topic: str,
    question: str,
    prior_history: str,
    current_transcript: str,
    candidates: list[str],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是李继刚圆桌方法中的主持人。你的任务是动态选择下一位最该发言的人，而不是平均点名。",
        },
        {
            "role": "user",
            "content": f"""主题：
{topic}

本轮问题：
{question}

前面轮次：
{prior_history or "暂无。"}

本轮已发生：
{current_transcript or "暂无。"}

候选发言者：
{", ".join(candidates)}

请只输出 JSON，不要解释：
{{"speaker":"候选者姓名或空字符串","stop_round":false,"reason":"为什么此刻该由此人发言或为什么应结束本轮"}}

选择原则：
- 谁最能质疑、补充、反驳、修正前文，就选谁。
- 如果本轮已经形成足够张力，可令 stop_round 为 true。
- speaker 必须来自候选发言者，或在 stop_round=true 时为空字符串。
""",
        },
    ]


def parse_speaker_selection(text: str, candidates: list[str]) -> tuple[str, bool]:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        stop_round = bool(data.get("stop_round"))
        speaker = str(data.get("speaker") or "").strip()
        if stop_round and not speaker:
            return "", True
        if speaker in candidates:
            return speaker, stop_round
    except Exception:
        pass

    for candidate in candidates:
        if candidate in stripped:
            return candidate, False
    return (candidates[0] if candidates else "", False)


def build_deepen_question(topic: str, last_moderator: str) -> str:
    core = last_moderator.strip() or topic
    core = core.replace("【本轮核心争议点】", "").strip()
    first_line = core.splitlines()[0] if core else topic
    return f"请不要推进新问题，继续深入上一轮核心争议：「{first_line}」。它最难、最容易被误解的地方是什么？"


def build_conclusion_messages(*, topic: str, history: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是李继刚圆桌方法中的主持人。现在用户选择“止”，你要结束讨论并生成知识网络。",
        },
        {
            "role": "user",
            "content": f"""主题：
{topic}

完整讨论记录：
{history}

请输出：
【全局总结】
【完整知识网络】
用 ASCII 图标出关键概念、人物立场、争议点及其关系。
【开放问题】
列出讨论中暴露但尚未穷尽的问题。
""",
        },
    ]


async def run_agent(
    *,
    client: SiliconFlow,
    store: CorpusStore,
    root: Path,
    person: str,
    topic: str,
    question: str,
    history: str,
    query_embedding: list[float],
    top_k: int,
    audit: bool,
) -> AgentResult:
    evidence = store.search(person=person, query_embedding=query_embedding, top_k=top_k)
    persona = read_persona(root, person)
    speech = await client.chat(
        build_agent_messages(
            person=person,
            persona=persona,
            topic=topic,
            question=question,
            history=history,
            evidence=evidence,
        )
    )
    audit_text = None
    if audit:
        audit_text = await client.chat(
            build_audit_messages(person=person, speech=speech, evidence=evidence),
            temperature=0.1,
        )
    return AgentResult(person=person, evidence=evidence, speech=speech, audit=audit_text)


async def run_dialogue_round(
    *,
    client: SiliconFlow,
    store: CorpusStore,
    root: Path,
    participants: list[str],
    topic: str,
    question: str,
    prior_history: str,
    query_embedding: list[float],
    top_k: int,
    audit: bool,
    round_number: int,
) -> RoundResult:
    results: list[AgentResult] = []
    candidates = list(participants)
    while candidates:
        current_transcript = "\n\n".join(format_agent_transcript(result) for result in results)
        if results:
            decision_text = await client.chat(
                build_speaker_selection_messages(
                    topic=topic,
                    question=question,
                    prior_history=prior_history,
                    current_transcript=current_transcript,
                    candidates=candidates,
                ),
                temperature=0.1,
                max_tokens=300,
            )
            person, stop_round = parse_speaker_selection(decision_text, candidates)
            if stop_round and results:
                break
        else:
            person = candidates[0]

        if person not in candidates:
            person = candidates[0]
        turn_history = build_turn_history(
            prior_history=prior_history,
            question=question,
            current_results=results,
        )
        result = await run_agent(
            client=client,
            store=store,
            root=root,
            person=person,
            topic=topic,
            question=question,
            history=turn_history,
            query_embedding=query_embedding,
            top_k=top_k,
            audit=audit,
        )
        results.append(result)
        candidates.remove(person)

    moderator = await client.chat(build_moderator_messages(topic=topic, question=question, results=results))
    history = append_round_to_history(
        prior_history,
        round_number=round_number,
        question=question,
        results=results,
        moderator=moderator,
    )
    return RoundResult(
        round_number=round_number,
        question=question,
        results=results,
        moderator=moderator,
        history=history,
    )


def write_session(
    *,
    session_dir: Path,
    topic: str,
    question: str,
    results: list[AgentResult],
    moderator: str,
    round_number: int = 1,
) -> None:
    round_dir = session_dir / f"round-{round_number:02d}"
    evidence_dir = round_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    topic_file = session_dir / "topic.md"
    if not topic_file.exists():
        topic_file.write_text(f"# 主题\n\n{topic}\n", encoding="utf-8")

    agents_md = []
    audit_md = []
    for result in results:
        agents_md.append(f"# {result.person}\n\n{result.speech}\n")
        if result.audit:
            audit_md.append(f"# {result.person}\n\n{result.audit}\n")
        (evidence_dir / f"{result.person}.md").write_text(format_evidence(result.evidence), encoding="utf-8")

    (round_dir / "agents.md").write_text("\n\n---\n\n".join(agents_md), encoding="utf-8")
    if audit_md:
        (round_dir / "audit.md").write_text("\n\n---\n\n".join(audit_md), encoding="utf-8")
    (round_dir / "moderator.md").write_text(moderator, encoding="utf-8")
    (round_dir / "question.md").write_text(f"# 第 {round_number} 轮问题\n\n{question}\n", encoding="utf-8")

    round_summary = "\n\n".join(
        [
            f"## 第 {round_number} 轮",
            f"### 本轮问题\n\n{question}",
            f"### 文件\n\n- `{round_dir.name}/agents.md`\n- `{round_dir.name}/moderator.md`\n- `{round_dir.name}/evidence/`",
        ]
    )
    rounds_file = session_dir / "rounds.md"
    existing_rounds = rounds_file.read_text(encoding="utf-8") if rounds_file.exists() else f"# 圆桌轮次：{topic}\n"
    if f"## 第 {round_number} 轮" not in existing_rounds:
        rounds_file.write_text(existing_rounds.rstrip() + "\n\n" + round_summary + "\n", encoding="utf-8")

    final = "\n\n".join(
        [
            f"# 圆桌：{topic}",
            f"## 当前最新轮次\n\n第 {round_number} 轮",
            f"## 本轮问题\n\n{question}",
            "## 人物发言",
            "\n\n---\n\n".join(agents_md),
            "## 主持人综述",
            moderator,
        ]
    )
    (session_dir / "final.md").write_text(final, encoding="utf-8")


async def run_roundtable(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    settings = load_settings(Path(args.config).resolve() if args.config else None)
    client = SiliconFlow(settings)
    store = CorpusStore(root / "indexes" / "roundtable.sqlite")

    participants = args.participants or store.indexed_people()
    if not participants:
        print("No participants found. Run scripts/ingest.py after adding materials.")
        return 1

    question = args.question or args.topic
    query_text = f"{args.topic}\n{question}"
    query_embedding = (await client.embed_texts([query_text]))[0]

    round_result = await run_dialogue_round(
        client=client,
        store=store,
        root=root,
        participants=participants,
        topic=args.topic,
        question=question,
        prior_history=args.history or "",
        query_embedding=query_embedding,
        top_k=args.top_k or settings.top_k,
        audit=args.audit,
        round_number=1,
    )

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    session_dir = root / "sessions" / f"{timestamp}-{slugify(args.topic)}"
    write_session(
        session_dir=session_dir,
        topic=args.topic,
        question=question,
        results=round_result.results,
        moderator=round_result.moderator,
        round_number=round_result.round_number,
    )
    print(f"session written: {session_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an evidence-grounded roundtable.")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="Project root")
    parser.add_argument("--config", help="Optional config.toml path")
    parser.add_argument("--topic", required=True, help="Roundtable topic")
    parser.add_argument("--question", help="Current round question; defaults to topic")
    parser.add_argument("--participants", nargs="*", help="Participant names")
    parser.add_argument("--history", help="Existing discussion context")
    parser.add_argument("--top-k", type=int, help="Evidence chunks per participant")
    parser.add_argument("--audit", action="store_true", help="Run evidence faithfulness audit")
    return parser


def main() -> int:
    parser = build_parser()
    return asyncio.run(run_roundtable(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
