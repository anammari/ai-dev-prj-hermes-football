"""Tracked files must not contain host-local paths.

The repository is read by reviewers and by agents on other machines. A path such as
``/Users/<name>/...`` or ``~/GitHub/...`` carries no meaning there, and it leaks the author's
directory layout into a public artifact. Product paths are different and stay: ``/app``,
``/corpus``, ``/opt/data`` and ``/var/run/docker.sock`` are part of the deployed system.

The check walks the tree rather than reading ``git ls-files`` because the test image has no
``.git``; the ignored directories below are what a checkout and a container share.
"""

from __future__ import annotations

import re
from pathlib import Path

from db.settings import REPO_ROOT

#: Directories that are generated, local-only, or a checkout's plumbing.
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "data",
    "node_modules",
}

#: Files with no suffix that still carry prose a reviewer reads.
TEXT_NAMES = {"Dockerfile", "Dockerfile.ollama", "Makefile", "alembic.ini", ".gitignore"}

TEXT_SUFFIXES = {
    ".example",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

#: Host-local shapes. `~/GitHub` and `copilot-worktrees` name the author's machine; the Windows
#: pattern is written with both separators so it matches either spelling.
LOCAL_PATH_PATTERNS = [
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"/Applications/"),
    re.compile(r"[A-Za-z]:\\\\Users"),
    re.compile(r"[A-Za-z]:\\Users"),
    re.compile(r"~/GitHub"),
    re.compile(r"copilot-worktrees"),
]


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # This file is the only place the patterns may appear: it is where they are defined.
        if path.resolve() == Path(__file__).resolve():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.name == ".env":
            continue
        if path.name in TEXT_NAMES or path.suffix in TEXT_SUFFIXES:
            files.append(path)
    return files


def test_no_host_local_paths_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in LOCAL_PATH_PATTERNS):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {line.strip()}")

    assert not offenders, "host-local paths in tracked files:\n" + "\n".join(offenders)
