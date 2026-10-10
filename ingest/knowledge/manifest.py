"""The corpus inventory: `manifest.yaml` on one side, the files on disk on the other.

`R-F6.5` makes this checkable: a file with no entry, an entry with no file, or an entry with no
source citation is a test failure. The rule exists because a corpus nobody can enumerate is a corpus
nobody can review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

MANIFEST_NAME = "manifest.yaml"

#: The seven question classes of `_docs/scoping.md` §4. A note that fits none of them does not belong
#: in the corpus; a note that fits two is normal.
QUESTION_CLASSES: tuple[str, ...] = (
    "formats",
    "tiebreakers",
    "qualification_relegation",
    "data_policy",
    "coverage_limits",
    "glossary",
    "multi_hop",
)

NOTE_STATUSES: tuple[str, ...] = ("draft", "reviewed", "retired")

REQUIRED_FIELDS: tuple[str, ...] = (
    "file",
    "title",
    "question_classes",
    "source",
    "owner",
    "status",
    "reviewed_at",
)


class ManifestError(ValueError):
    """The manifest and the corpus disagree, or an entry is incomplete."""


@dataclass(frozen=True, slots=True)
class NoteEntry:
    file: str
    title: str
    question_classes: tuple[str, ...]
    competitions: tuple[str, ...]
    source: str
    owner: str
    status: str
    reviewed_at: date
    path: Path


@dataclass(slots=True)
class Manifest:
    version: int
    notes: list[NoteEntry] = field(default_factory=list)

    def by_file(self) -> dict[str, NoteEntry]:
        return {note.file: note for note in self.notes}


def _as_tuple(value: Any, what: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ManifestError(f"{where}: {what} must be a list, not a string")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{where}: {what} must be a list of strings")
    return tuple(value)


def _as_date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ManifestError(f"{where}: reviewed_at is not an ISO date: {value!r}") from exc
    raise ManifestError(f"{where}: reviewed_at is required and must be an ISO date")


def discover_note_files(knowledge_dir: Path) -> list[str]:
    """Every `.md` under the corpus, relative to it, POSIX-style and sorted.

    There are no exceptions: a stray README is a missing manifest entry, which is exactly the
    failure this is meant to surface.
    """
    if not knowledge_dir.is_dir():
        raise ManifestError(f"knowledge directory not found: {knowledge_dir}")
    return sorted(path.relative_to(knowledge_dir).as_posix() for path in knowledge_dir.rglob("*.md"))


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a note into its YAML front-matter and its body.

    Returns `({}, text)` when there is no front-matter, so callers can decide whether that is an
    error rather than having it thrown from here.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, text
    front = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(front, dict):
        raise ManifestError("front-matter must be a mapping")
    return front, "\n".join(lines[end + 1 :])


def load_manifest(knowledge_dir: Path) -> Manifest:
    """Parse and validate `manifest.yaml`, resolving each entry's path."""
    manifest_path = knowledge_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ManifestError(f"missing {manifest_path}")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ManifestError(f"{MANIFEST_NAME} must be a mapping")

    notes: list[NoteEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(raw.get("notes") or []):
        where = f"{MANIFEST_NAME}: notes[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{where}: must be a mapping")
        missing = [name for name in REQUIRED_FIELDS if not item.get(name)]
        if missing:
            raise ManifestError(f"{where}: missing {', '.join(missing)}")

        file = str(item["file"]).strip()
        where = f"{MANIFEST_NAME}: {file}"
        if file in seen:
            raise ManifestError(f"{where}: listed twice")
        seen.add(file)
        if file.startswith("/") or ".." in Path(file).parts:
            raise ManifestError(f"{where}: must be a path inside the corpus")

        classes = _as_tuple(item.get("question_classes"), "question_classes", where)
        unknown = [name for name in classes if name not in QUESTION_CLASSES]
        if unknown:
            raise ManifestError(f"{where}: unknown question classes: {', '.join(unknown)}")
        if not classes:
            raise ManifestError(f"{where}: question_classes must not be empty")

        status = str(item["status"]).strip()
        if status not in NOTE_STATUSES:
            raise ManifestError(f"{where}: status must be one of {', '.join(NOTE_STATUSES)}")

        notes.append(
            NoteEntry(
                file=file,
                title=str(item["title"]).strip(),
                question_classes=classes,
                competitions=_as_tuple(item.get("competitions"), "competitions", where),
                source=str(item["source"]).strip(),
                owner=str(item["owner"]).strip(),
                status=status,
                reviewed_at=_as_date(item["reviewed_at"], where),
                path=knowledge_dir / file,
            )
        )
    return Manifest(version=int(raw.get("version") or 1), notes=notes)


def check_corpus(knowledge_dir: Path) -> list[str]:
    """Every reason the manifest and the corpus disagree. Empty list means they agree."""
    problems: list[str] = []
    manifest = load_manifest(knowledge_dir)
    entries = manifest.by_file()
    on_disk = discover_note_files(knowledge_dir)

    for missing in sorted(set(entries) - set(on_disk)):
        problems.append(f"{missing}: listed in {MANIFEST_NAME} but not on disk")
    for undeclared in sorted(set(on_disk) - set(entries)):
        problems.append(f"{undeclared}: on disk but not listed in {MANIFEST_NAME}")

    for file in sorted(set(on_disk) & set(entries)):
        entry = entries[file]
        if entry.status == "retired":
            continue
        text = entry.path.read_text(encoding="utf-8")
        front, _ = parse_front_matter(text)
        if not front:
            problems.append(f"{file}: no YAML front-matter")
            continue
        problems.extend(_compare_front_matter(entry, front, file))
    return problems


def _normalised(value: object) -> str:
    """Whitespace-collapsed comparison: a folded YAML scalar and a single line are the same string."""
    return " ".join(str(value).split())


def _compare_front_matter(entry: NoteEntry, front: dict[str, Any], file: str) -> list[str]:
    """The note and the manifest must say the same thing about the note, on all seven keys.

    A note whose front-matter has drifted from the manifest is a note nobody is maintaining, which is
    the failure `R-F6.1a` calls "reviewed like code" is supposed to prevent.
    """
    problems: list[str] = []
    where = f"{file}: front-matter"
    plain: dict[str, object] = {
        "file": entry.file,
        "title": entry.title,
        "source": entry.source,
        "owner": entry.owner,
        "status": entry.status,
    }
    for key, value in plain.items():
        if key not in front:
            problems.append(f"{where} is missing {key}")
        elif _normalised(front[key]) != _normalised(value):
            problems.append(f"{where} {key} does not match {MANIFEST_NAME}")
    for key in ("question_classes", "competitions"):
        if key not in front:
            problems.append(f"{where} is missing {key}")
            continue
        values = _as_tuple(front.get(key), key, where)
        if tuple(sorted(values)) != tuple(sorted(getattr(entry, key))):
            problems.append(f"{where} {key} does not match {MANIFEST_NAME}")
    if "reviewed_at" not in front:
        problems.append(f"{where} is missing reviewed_at")
    else:
        try:
            if _as_date(front["reviewed_at"], where) != entry.reviewed_at:
                problems.append(f"{where} reviewed_at does not match {MANIFEST_NAME}")
        except ManifestError as exc:
            problems.append(str(exc))
    return problems
