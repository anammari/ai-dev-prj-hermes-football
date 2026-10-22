"""Cheap, deterministic checks on a complex answer before it is sent.

The composer is told to cite the data timestamp or the note file. This verifier checks that it did, and
that the citation matches a result the gateway actually collected. It is not a full claim checker; it is
the guard that keeps a cloud-generated draft from losing its grounding. A failed check falls back to the
deterministic composer.
"""

from __future__ import annotations


def _stamp_date(payload: dict) -> str | None:
    raw = payload.get("data_as_of") or payload.get("as_of")
    if not raw:
        return None
    return str(raw)[:10]


def verify_complex(text: str, *, route: str, results: dict) -> bool:
    if not text or len(text.strip()) < 20:
        return False
    lowered = text.lower()
    if route == "tool":
        dates = [date for date in (_stamp_date(payload) for payload in results.values()) if date]
        if not dates:
            return False
        return "source: football-data.org" in lowered and any(date in text for date in dates)
    if route == "knowledge":
        files = []
        for payload in results.values():
            for hit in payload.get("hits") or []:
                if hit.get("source_file"):
                    files.append(str(hit["source_file"]))
        return "source:" in lowered and any(file in text for file in files)
    return False
