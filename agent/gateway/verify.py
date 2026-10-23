"""Cheap, deterministic checks on a complex answer before it is sent.

The composer is told to cite the data timestamp or the note file. This verifier checks that it did, and
that the citation matches a result the gateway actually collected. It is not a full claim checker; it is
the guard that keeps a cloud-generated draft from losing its grounding. A failed check falls back to the
deterministic composer.
"""

from __future__ import annotations

from datetime import datetime


def _stamp_parts(payload: dict) -> tuple[str, str] | None:
    raw = payload.get("data_as_of") or payload.get("as_of")
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M")


def verify_complex(text: str, *, route: str, results: dict) -> bool:
    if not text or len(text.strip()) < 20:
        return False
    lowered = text.lower()
    if route == "tool":
        stamps = [stamp for stamp in (_stamp_parts(payload) for payload in results.values()) if stamp]
        if not stamps:
            return False
        return "as of" in lowered and "source: football-data.org" in lowered and any(
            date in text and time in text for date, time in stamps
        )
    if route == "knowledge":
        files = []
        for payload in results.values():
            for hit in payload.get("hits") or []:
                if hit.get("source_file"):
                    files.append(str(hit["source_file"]))
        return "source:" in lowered and any(file in text for file in files)
    return False
