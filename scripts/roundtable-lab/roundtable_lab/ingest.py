from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import PROJECT_ROOT, load_settings
from .siliconflow import SiliconFlow
from .store import CorpusStore, file_sha256
from .textio import chunk_text, extract_text, is_supported


def iter_material_files(materials_dir: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for person_dir in sorted(path for path in materials_dir.iterdir() if path.is_dir()):
        sources = person_dir / "sources"
        search_root = sources if sources.exists() else person_dir
        for path in sorted(search_root.rglob("*")):
            if is_supported(path):
                files.append((person_dir.name, path))
    return files


async def embed_in_batches(client: SiliconFlow, chunks: list[str], batch_size: int) -> list[list[float]]:
    batches = [chunks[start : start + batch_size] for start in range(0, len(chunks), batch_size)]
    batch_results = await asyncio.gather(*(client.embed_texts(batch) for batch in batches))
    embeddings: list[list[float]] = []
    for result in batch_results:
        embeddings.extend(result)
    return embeddings


async def run_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    settings = load_settings(Path(args.config).resolve() if args.config else None)
    store = CorpusStore(root / "indexes" / "roundtable.sqlite")
    client = SiliconFlow(settings)

    materials_dir = Path(args.materials).resolve() if args.materials else root / "materials"
    files = iter_material_files(materials_dir)
    if not files:
        print(f"No supported files found under {materials_dir}")
        return 1

    indexed_docs = 0
    skipped_docs = 0
    indexed_chunks = 0

    if args.rebuild and store.db_path.exists():
        store.conn.execute("DELETE FROM documents")
        store.conn.commit()

    for person, path in files:
        sha256 = file_sha256(path)
        stat = path.stat()
        if not args.rebuild and store.document_current(path, sha256, settings.embed_model):
            skipped_docs += 1
            continue

        text = extract_text(path)
        chunks = chunk_text(text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        if not chunks:
            print(f"skip empty: {person} {path}", flush=True)
            continue

        print(f"embedding {person}: {path.name} ({len(chunks)} chunks)", flush=True)
        embeddings = await embed_in_batches(client, chunks, settings.embed_batch_size)
        count = store.replace_document(
            person=person,
            path=path,
            sha256=sha256,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=settings.embed_model,
        )
        indexed_docs += 1
        indexed_chunks += count
        print(f"indexed {person}: {path.name} ({count} chunks)", flush=True)

    print(
        f"done: indexed_docs={indexed_docs}, skipped_docs={skipped_docs}, "
        f"indexed_chunks={indexed_chunks}, total_chunks={store.count_chunks()}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Embed local roundtable materials with SiliconFlow.")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="Project root")
    parser.add_argument("--materials", help="Materials directory; defaults to ROOT/materials")
    parser.add_argument("--config", help="Optional config.toml path")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all indexed documents")
    return parser


def main() -> int:
    parser = build_parser()
    return asyncio.run(run_ingest(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
