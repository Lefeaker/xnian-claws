from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, Query
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, load_settings
from .roundtable import (
    AgentResult,
    append_round_to_history,
    build_conclusion_messages,
    build_deepen_question,
    build_moderator_messages,
    build_opening_question,
    build_speaker_selection_messages,
    build_turn_history,
    format_agent_transcript,
    parse_speaker_selection,
    run_agent,
    slugify,
    write_session,
)
from .siliconflow import SiliconFlow
from .store import ChunkHit, CorpusStore
from .textio import is_supported


STATIC_DIR = PROJECT_ROOT / "web" / "static"
app = FastAPI(title="Roundtable Lab")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def disable_browser_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@dataclass
class BrowserRoundtableSession:
    session_id: str
    topic: str
    participants: list[str]
    history: str = ""
    round_number: int = 0
    session_dir: Path | None = None
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%dT%H%M%S"))
    last_question: str = ""
    last_moderator: str = ""
    concluded: bool = False


ACTIVE_SESSIONS: dict[str, BrowserRoundtableSession] = {}


def session_metadata_path(session_dir: Path) -> Path:
    return session_dir / "session.json"


def session_notes_path(session_dir: Path) -> Path:
    return session_dir / "notes.md"


def load_session_notes(session_dir: Path) -> str:
    path = session_notes_path(session_dir)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_session_notes(session_dir: Path, notes: str) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    session_notes_path(session_dir).write_text(notes, encoding="utf-8")


def save_browser_session_metadata(session: BrowserRoundtableSession) -> None:
    if session.session_dir is None:
        return
    session.session_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session.session_id,
        "topic": session.topic,
        "participants": session.participants,
        "round_number": session.round_number,
        "created_at": session.created_at,
        "last_question": session.last_question,
        "last_moderator": session.last_moderator,
        "concluded": session.concluded,
    }
    session_metadata_path(session.session_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if session.history:
        (session.session_dir / "transcript.md").write_text(session.history, encoding="utf-8")


def load_browser_session(session_dir: Path) -> BrowserRoundtableSession:
    metadata = json.loads(session_metadata_path(session_dir).read_text(encoding="utf-8"))
    history_path = session_dir / "transcript.md"
    history = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
    session = BrowserRoundtableSession(
        session_id=metadata["session_id"],
        topic=metadata["topic"],
        participants=list(metadata.get("participants", [])),
        history=history,
        round_number=int(metadata.get("round_number", 0)),
        session_dir=session_dir,
        created_at=metadata.get("created_at", session_dir.name.split("-", 1)[0]),
        last_question=metadata.get("last_question", ""),
        last_moderator=metadata.get("last_moderator", ""),
        concluded=bool(metadata.get("concluded", False)),
    )
    ACTIVE_SESSIONS[session.session_id] = session
    return session


def infer_legacy_session_metadata(session_dir: Path) -> BrowserRoundtableSession | None:
    topic_path = session_dir / "topic.md"
    transcript_path = session_dir / "transcript.md"
    if not topic_path.exists() or not transcript_path.exists():
        return None
    topic_text = topic_path.read_text(encoding="utf-8")
    topic = topic_text.replace("# 主题", "", 1).strip().splitlines()[0].strip() if topic_text.strip() else session_dir.name
    history = transcript_path.read_text(encoding="utf-8")
    round_number = len(list(session_dir.glob("round-[0-9][0-9]")))
    participants: list[str] = []
    agents_path = session_dir / "round-01" / "agents.md"
    if agents_path.exists():
        for line in agents_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                participants.append(line[2:].strip())
    session = BrowserRoundtableSession(
        session_id=uuid4().hex,
        topic=topic,
        participants=participants,
        history=history,
        round_number=round_number,
        session_dir=session_dir,
        created_at=session_dir.name.split("-", 1)[0],
    )
    save_browser_session_metadata(session)
    return session


def parse_people_markdown(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    sections = path.read_text(encoding="utf-8").split("\n\n---\n\n")
    people: dict[str, str] = {}
    for section in sections:
        lines = section.strip().splitlines()
        if not lines or not lines[0].startswith("# "):
            continue
        person = lines[0][2:].strip()
        content = "\n".join(lines[1:]).strip()
        people[person] = content
    return people


def parse_saved_rounds(session_dir: Path) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = []
    for round_dir in sorted(path for path in session_dir.glob("round-[0-9][0-9]") if path.is_dir()):
        question_text = ""
        question_path = round_dir / "question.md"
        if question_path.exists():
            raw = question_path.read_text(encoding="utf-8").splitlines()
            question_text = "\n".join(line for line in raw if not line.startswith("#")).strip()
        agents = parse_people_markdown(round_dir / "agents.md")
        audits = parse_people_markdown(round_dir / "audit.md")
        rounds.append(
            {
                "round": round_dir.name,
                "question": question_text,
                "agents": [
                    {
                        "person": person,
                        "content": content,
                        "audit": audits.get(person, ""),
                    }
                    for person, content in agents.items()
                ],
                "moderator": (round_dir / "moderator.md").read_text(encoding="utf-8").strip()
                if (round_dir / "moderator.md").exists()
                else "",
            }
        )
    return rounds


def list_saved_sessions(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    if not root.exists():
        return sessions
    for session_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        metadata_path = session_metadata_path(session_dir)
        if not metadata_path.exists():
            if infer_legacy_session_metadata(session_dir) is None:
                continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sessions.append(
            {
                "session_id": metadata["session_id"],
                "topic": metadata.get("topic", session_dir.name),
                "participants": metadata.get("participants", []),
                "round_number": metadata.get("round_number", 0),
                "created_at": metadata.get("created_at", ""),
                "concluded": metadata.get("concluded", False),
                "session_dir": str(session_dir),
                "notes_preview": load_session_notes(session_dir)[:120],
            }
        )
        if len(sessions) >= limit:
            break
    return sessions


def create_browser_session(topic: str, participants: list[str]) -> BrowserRoundtableSession:
    session_id = uuid4().hex
    session = BrowserRoundtableSession(
        session_id=session_id,
        topic=topic,
        participants=participants,
        session_dir=PROJECT_ROOT / "sessions" / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{slugify(topic)}",
    )
    ACTIVE_SESSIONS[session_id] = session
    return session


def get_browser_session(
    *,
    session_id: str | None,
    topic: str,
    participants: list[str],
    reset: bool,
) -> BrowserRoundtableSession:
    if session_id and session_id in ACTIVE_SESSIONS and not reset:
        return ACTIVE_SESSIONS[session_id]
    if session_id and not reset:
        for item in list_saved_sessions(PROJECT_ROOT / "sessions", limit=100):
            if item["session_id"] == session_id:
                return load_browser_session(Path(item["session_dir"]))
    if reset or not session_id or session_id not in ACTIVE_SESSIONS:
        return create_browser_session(topic, participants)
    return ACTIVE_SESSIONS[session_id]


def update_session_history(
    session: BrowserRoundtableSession,
    *,
    question: str,
    results: list[AgentResult],
    moderator: str,
) -> None:
    session.round_number += 1
    session.history = append_round_to_history(
        session.history,
        round_number=session.round_number,
        question=question,
        results=results,
        moderator=moderator,
    )
    session.last_question = question
    session.last_moderator = moderator


def apply_roundtable_command(
    session: BrowserRoundtableSession,
    *,
    command: str,
    provided_question: str,
    new_participant: str,
) -> tuple[str, str]:
    normalized = command.strip() or "可"
    if normalized == "止":
        return "", "conclude"
    if normalized == "引入新人物":
        person = new_participant.strip()
        if person and person not in session.participants:
            session.participants.append(person)
        question = provided_question.strip() or f"请新加入的「{person or '新人物'}」先就当前争议表态，并回应前文最关键的分歧。"
        return question, "round"
    if normalized == "深入此节":
        return provided_question.strip() or build_deepen_question(session.topic, session.last_moderator or session.last_question), "round"
    if provided_question.strip():
        return provided_question.strip(), "round"
    if session.round_number == 0:
        return build_opening_question(session.topic), "round"
    return session.last_question or session.topic, "round"


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def build_material_status(root: Path, indexed_counts: dict[str, int] | None = None) -> list[dict[str, Any]]:
    indexed_counts = indexed_counts or {}
    materials_dir = root / "materials"
    if not materials_dir.exists():
        return []

    people: list[dict[str, Any]] = []
    for person_dir in sorted(path for path in materials_dir.iterdir() if path.is_dir()):
        sources_dir = person_dir / "sources"
        search_root = sources_dir if sources_dir.exists() else person_dir
        sources = [
            path
            for path in sorted(search_root.iterdir())
            if is_supported(path)
        ]
        people.append(
            {
                "person": person_dir.name,
                "source_count": len(sources),
                "indexed_chunks": indexed_counts.get(person_dir.name, 0),
                "sources": [
                    {
                        "name": path.name,
                        "path": str(path),
                        "kind": "directory-epub" if path.is_dir() else path.suffix.lower().lstrip("."),
                        "bytes": _path_size(path),
                    }
                    for path in sources
                ],
            }
        )
    return people


def indexed_counts(root: Path) -> dict[str, int]:
    db_path = root / "indexes" / "roundtable.sqlite"
    if not db_path.exists():
        return {}
    store = CorpusStore(db_path)
    try:
        return {person: store.count_chunks(person) for person in store.indexed_people()}
    finally:
        store.close()


def chunk_hit_to_dict(hit: ChunkHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "person": hit.person,
        "path": hit.path,
        "chunk_index": hit.chunk_index,
        "score": round(hit.score, 4),
        "text": hit.text,
    }


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def parse_participants(raw: str | None, store: CorpusStore) -> list[str]:
    if not raw:
        return store.indexed_people()
    return [item.strip() for item in raw.split(",") if item.strip()]


async def roundtable_stream(
    *,
    topic: str,
    question: str | None,
    participants_raw: str | None,
    session_id: str | None,
    reset: bool,
    command: str,
    new_participant: str,
    audit: bool,
    top_k: int | None,
) -> AsyncIterator[str]:
    settings = load_settings()
    if not settings.chat_api_key:
        yield sse_event("error", {"message": "缺少 ROUNDTABLE_CHAT_API_KEY，请先填写 .env。"})
        return
    if not settings.embed_api_key:
        yield sse_event("error", {"message": "缺少 SILICONFLOW_API_KEY，请先填写 .env。"})
        return

    store = CorpusStore(PROJECT_ROOT / "indexes" / "roundtable.sqlite")
    try:
        participants = parse_participants(participants_raw, store)
        if not participants:
            yield sse_event("error", {"message": "没有可用人物索引，请先运行 scripts/ingest.py。"})
            return

        session = get_browser_session(
            session_id=session_id,
            topic=topic,
            participants=participants,
            reset=reset,
        )
        current_question, action = apply_roundtable_command(
            session,
            command=command,
            provided_question=question or "",
            new_participant=new_participant or "",
        )
        client = SiliconFlow(settings)
        if action == "conclude":
            if not session.history.strip():
                yield sse_event("error", {"message": "当前 session 还没有讨论记录，无法结束总结。"})
                return
            yield sse_event("status", {"message": "主持人正在生成全局知识网络"})
            conclusion = await client.chat(build_conclusion_messages(topic=session.topic, history=session.history))
            session.concluded = True
            session_dir = session.session_dir or PROJECT_ROOT / "sessions" / f"{session.created_at}-{slugify(session.topic)}"
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "knowledge-network.md").write_text(conclusion, encoding="utf-8")
            (session_dir / "transcript.md").write_text(session.history, encoding="utf-8")
            save_browser_session_metadata(session)
            yield sse_event("conclusion", {"content": conclusion})
            yield sse_event(
                "done",
                {
                    "session_dir": str(session_dir),
                    "session_id": session.session_id,
                    "round_number": session.round_number,
                    "concluded": True,
                },
            )
            return

        yield sse_event(
            "status",
            {
                "message": "正在生成查询向量",
                "participants": session.participants,
                "topic": topic,
                "question": current_question,
                "session_id": session.session_id,
                "round_number": session.round_number + 1,
                "participants": session.participants,
            },
        )
        query_embedding = (await client.embed_texts([f"{topic}\n{current_question}"]))[0]
        yield sse_event(
            "status",
            {
                "message": f"第 {session.round_number + 1} 轮开始：人物将按顺序回应前文",
                "history_chars": len(session.history),
            },
        )

        results: list[AgentResult] = []
        candidates = list(session.participants)
        while candidates:
            current_transcript = "\n\n".join(format_agent_transcript(result) for result in results)
            if results:
                decision_text = await client.chat(
                    build_speaker_selection_messages(
                        topic=topic,
                        question=current_question,
                        prior_history=session.history,
                        current_transcript=current_transcript,
                        candidates=candidates,
                    ),
                    temperature=0.1,
                    max_tokens=300,
                )
                person, stop_round = parse_speaker_selection(decision_text, candidates)
                if stop_round and results:
                    yield sse_event("status", {"message": "主持人判断本轮张力已足够，结束人物发言"})
                    break
            else:
                person = candidates[0]
            if person not in candidates:
                person = candidates[0]
            yield sse_event(
                "status",
                {
                    "message": f"主持人选择 {person} 发言：正在阅读前文并检索自己的材料",
                    "person": person,
                },
            )
            turn_history = build_turn_history(
                prior_history=session.history,
                question=current_question,
                current_results=results,
            )
            result = await run_agent(
                client=client,
                store=store,
                root=PROJECT_ROOT,
                person=person,
                topic=topic,
                question=current_question,
                history=turn_history,
                query_embedding=query_embedding,
                top_k=top_k or settings.top_k,
                audit=audit,
            )
            results.append(result)
            candidates.remove(person)
            yield sse_event(
                "agent",
                {
                    "person": result.person,
                    "speech": result.speech,
                    "audit": result.audit,
                    "evidence": [chunk_hit_to_dict(hit) for hit in result.evidence],
                },
            )

        yield sse_event("status", {"message": "主持人正在综合争议"})
        moderator = await client.chat(
            build_moderator_messages(topic=topic, question=current_question, results=results)
        )

        update_session_history(
            session,
            question=current_question,
            results=results,
            moderator=moderator,
        )
        session_dir = session.session_dir or PROJECT_ROOT / "sessions" / f"{session.created_at}-{slugify(topic)}"
        write_session(
            session_dir=session_dir,
            topic=topic,
            question=current_question,
            results=results,
            moderator=moderator,
            round_number=session.round_number,
        )
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "transcript.md").write_text(session.history, encoding="utf-8")
        save_browser_session_metadata(session)
        yield sse_event("moderator", {"content": moderator})
        yield sse_event(
            "done",
            {
                "session_dir": str(session_dir),
                "session_id": session.session_id,
                "round_number": session.round_number,
            },
        )
    except Exception as exc:
        yield sse_event("error", {"message": str(exc)})
    finally:
        store.close()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status() -> JSONResponse:
    settings = load_settings()
    return JSONResponse(
        {
            "has_api_key": bool(settings.chat_api_key and settings.embed_api_key),
            "has_chat_key": bool(settings.chat_api_key),
            "has_embed_key": bool(settings.embed_api_key),
            "chat_model": settings.chat_model,
            "embed_model": settings.embed_model,
            "people": build_material_status(PROJECT_ROOT, indexed_counts(PROJECT_ROOT)),
        }
    )


@app.get("/api/sessions")
async def sessions() -> JSONResponse:
    return JSONResponse({"sessions": list_saved_sessions(PROJECT_ROOT / "sessions")})


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: str) -> JSONResponse:
    for item in list_saved_sessions(PROJECT_ROOT / "sessions", limit=100):
        if item["session_id"] == session_id:
            session = load_browser_session(Path(item["session_dir"]))
            return JSONResponse(
                {
                    **item,
                    "history": session.history,
                    "last_question": session.last_question,
                    "last_moderator": session.last_moderator,
                    "notes": load_session_notes(Path(item["session_dir"])),
                    "rounds": parse_saved_rounds(Path(item["session_dir"])),
                }
            )
    return JSONResponse({"error": "session not found"}, status_code=404)


@app.post("/api/sessions/{session_id}/notes")
async def session_notes(session_id: str, payload: dict[str, str] = Body(...)) -> JSONResponse:
    for item in list_saved_sessions(PROJECT_ROOT / "sessions", limit=100):
        if item["session_id"] == session_id:
            notes = payload.get("notes", "")
            save_session_notes(Path(item["session_dir"]), notes)
            if session_id in ACTIVE_SESSIONS:
                ACTIVE_SESSIONS[session_id].session_dir = Path(item["session_dir"])
            return JSONResponse({"ok": True})
    return JSONResponse({"error": "session not found"}, status_code=404)


@app.get("/api/roundtable/stream")
async def stream(
    topic: str = Query(..., min_length=1),
    question: str | None = None,
    participants: str | None = None,
    session_id: str | None = None,
    reset: bool = False,
    command: str = "可",
    new_participant: str = "",
    audit: bool = True,
    top_k: int | None = Query(default=None, ge=1, le=20),
) -> StreamingResponse:
    return StreamingResponse(
        roundtable_stream(
            topic=topic,
            question=question,
            participants_raw=participants,
            session_id=session_id,
            reset=reset,
            command=command,
            new_participant=new_participant,
            audit=audit,
            top_k=top_k,
        ),
        media_type="text/event-stream",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Roundtable Lab local web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    import uvicorn

    args = build_parser().parse_args()
    uvicorn.run("roundtable_lab.server:app", host=args.host, port=args.port)
    return 0
