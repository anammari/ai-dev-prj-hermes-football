"""Command line entry point for the notes corpus.

    python -m ingest.knowledge check                  # manifest vs files, no database, no network
    python -m ingest.knowledge index [--force]        # embed changed notes into the database
    python -m ingest.knowledge search "how does the playoff work"

`check` is the CI job: it needs nothing but the repository.
"""

from __future__ import annotations

import argparse
import sys

from db.session import create_db_engine, create_session_factory, session_scope
from db.settings import Settings
from ingest.knowledge.embedding import OllamaEmbedder
from ingest.knowledge.indexer import index_corpus, search_knowledge
from ingest.knowledge.manifest import ManifestError, check_corpus


def _cmd_check(settings: Settings) -> int:
    problems = check_corpus(settings.knowledge_dir)
    if problems:
        print("corpus does not match the manifest:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"corpus ok: {settings.knowledge_dir}")
    return 0


def _cmd_index(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    with (
        OllamaEmbedder(
            host=settings.ollama_host, model=settings.embedding_model, dim=settings.embedding_dim
        ) as embedder,
        session_scope(factory) as session,
    ):
        report = index_corpus(session, settings, embedder=embedder, force=args.force, only=set(args.only) or None)
    print(report.summary())
    for path in report.indexed:
        print(f"  indexed   {path}")
    for path in report.unchanged:
        print(f"  unchanged {path}")
    for path in report.removed:
        print(f"  removed   {path}")
    return 0


def _cmd_search(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    with (
        OllamaEmbedder(
            host=settings.ollama_host, model=settings.embedding_model, dim=settings.embedding_dim
        ) as embedder,
        session_scope(factory) as session,
    ):
        hits = search_knowledge(session, embedder, args.query, limit=args.limit)
    if not hits:
        print("no passages: the corpus does not cover this question (this is an answer, not an error)")
        return 0
    for chunk, score in hits:
        print(f"{score:.3f}  {chunk.source_file}  ::  {chunk.heading}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest.knowledge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate the manifest against the files (no database, no network)")

    index = sub.add_parser("index", help="embed changed notes into knowledge_chunks")
    index.add_argument("--force", action="store_true", help="re-embed every note, ignoring content hashes")
    index.add_argument("--only", action="append", default=[], metavar="FILE", help="restrict to a file (repeatable)")

    search = sub.add_parser("search", help="show the passages a question would retrieve")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    try:
        if args.command == "check":
            return _cmd_check(settings)
        if args.command == "index":
            return _cmd_index(settings, args)
        return _cmd_search(settings, args)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
