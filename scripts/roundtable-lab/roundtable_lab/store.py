from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: int
    person: str
    path: str
    chunk_index: int
    score: float
    text: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_dir():
        for item in sorted(child for child in path.rglob("*") if child.is_file()):
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            with item.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def embedding_to_blob(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


class CorpusStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self.ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              person TEXT NOT NULL,
              path TEXT NOT NULL UNIQUE,
              sha256 TEXT NOT NULL,
              size INTEGER NOT NULL,
              mtime_ns INTEGER NOT NULL,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chunks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
              person TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              text TEXT NOT NULL,
              text_hash TEXT NOT NULL,
              embedding BLOB NOT NULL,
              embedding_dim INTEGER NOT NULL,
              embedding_model TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(doc_id, chunk_index)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_person ON chunks(person);
            CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(embedding_model);
            """
        )
        self.conn.commit()

    def document_current(self, path: Path, sha256: str, embedding_model: str) -> bool:
        row = self.conn.execute(
            """
            SELECT d.id
            FROM documents d
            WHERE d.path = ? AND d.sha256 = ?
              AND EXISTS (
                SELECT 1 FROM chunks c
                WHERE c.doc_id = d.id AND c.embedding_model = ?
              )
            """,
            (str(path), sha256, embedding_model),
        ).fetchone()
        return row is not None

    def replace_document(
        self,
        *,
        person: str,
        path: Path,
        sha256: str,
        size: int,
        mtime_ns: int,
        chunks: list[str],
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")

        self.conn.execute("DELETE FROM documents WHERE path = ?", (str(path),))
        cursor = self.conn.execute(
            """
            INSERT INTO documents(person, path, sha256, size, mtime_ns)
            VALUES (?, ?, ?, ?, ?)
            """,
            (person, str(path), sha256, size, mtime_ns),
        )
        doc_id = int(cursor.lastrowid)
        rows = []
        for index, (text, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            rows.append(
                (
                    doc_id,
                    person,
                    index,
                    text,
                    text_hash,
                    embedding_to_blob(embedding),
                    len(embedding),
                    embedding_model,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO chunks(
              doc_id, person, chunk_index, text, text_hash,
              embedding, embedding_dim, embedding_model
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def indexed_people(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT person FROM chunks ORDER BY person").fetchall()
        return [str(row["person"]) for row in rows]

    def count_chunks(self, person: str | None = None) -> int:
        if person:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE person = ?", (person,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return int(row["n"])

    def search(self, *, person: str, query_embedding: list[float], top_k: int) -> list[ChunkHit]:
        query = np.asarray(query_embedding, dtype="<f4")
        rows = self.conn.execute(
            """
            SELECT c.id, c.person, d.path, c.chunk_index, c.text, c.embedding
            FROM chunks c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.person = ?
            """,
            (person,),
        ).fetchall()

        hits: list[ChunkHit] = []
        for row in rows:
            score = cosine(query, blob_to_embedding(row["embedding"]))
            hits.append(
                ChunkHit(
                    chunk_id=int(row["id"]),
                    person=str(row["person"]),
                    path=str(row["path"]),
                    chunk_index=int(row["chunk_index"]),
                    score=score,
                    text=str(row["text"]),
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]
