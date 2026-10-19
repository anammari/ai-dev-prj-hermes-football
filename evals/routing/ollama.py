"""Minimal Ollama client for the spike.

Two endpoints only:

- `POST /v1/systemone` for decision models, which return typed choices and calibrated
  probabilities instead of generated text;
- `GET /api/tags` and `GET /api/version` to record what actually ran in the results artifact.

The spike is the only caller. It never touches the production `ollama` service, and it never sends a
label, an expected tool or a rationale: the caller passes the user message as `state` and the label set
as `questions`, which is all either model sees.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class OllamaError(RuntimeError):
    """The spike server is unreachable, missing a model, or answered with an unexpected shape."""


@dataclass(frozen=True)
class Answer:
    label: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    size: int


class SystemOne:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> SystemOne:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def ask(self, state: str, questions: dict) -> dict[str, Answer]:
        payload = {"model": self.model, "state": state, "questions": questions}
        try:
            response = self._client.post("/v1/systemone", json=payload)
        except httpx.HTTPError as error:
            raise OllamaError(f"{self.model}: request failed: {error}") from error
        if response.status_code != 200:
            raise OllamaError(f"{self.model}: HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as error:
            raise OllamaError(f"{self.model}: response was not JSON") from error
        if not isinstance(body, dict):
            raise OllamaError(f"{self.model}: response is not a JSON object")
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise OllamaError(f"{self.model}: response has no answers object")

        parsed: dict[str, Answer] = {}
        for name in questions:
            entry = answers.get(name)
            if not isinstance(entry, dict) or "choice" not in entry:
                raise OllamaError(f"{self.model}: no choice for question {name!r}")
            probabilities = entry.get("probabilities") or {}
            if not isinstance(probabilities, dict):
                raise OllamaError(f"{self.model}: probabilities for {name!r} are not an object")
            try:
                confidence = float(entry.get("confidence", 0.0))
                parsed_probabilities = {str(key): float(value) for key, value in probabilities.items()}
            except (TypeError, ValueError) as error:
                raise OllamaError(f"{self.model}: malformed number for {name!r}") from error
            parsed[name] = Answer(
                label=str(entry["choice"]),
                confidence=max(0.0, min(1.0, confidence)),
                probabilities=parsed_probabilities,
            )
        return parsed


class OllamaProbe:
    """Read-only facts about the running spike server, for the results artifact."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> OllamaProbe:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def version(self) -> str:
        return self._get("/api/version").get("version", "unknown")

    def models(self) -> dict[str, ModelInfo]:
        body = self._get("/api/tags")
        entries = body.get("models", [])
        if not isinstance(entries, list):
            raise OllamaError("spike server /api/tags: models is not a list")
        result: dict[str, ModelInfo] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("model")
            if name:
                result[str(name)] = ModelInfo(
                    name=str(name),
                    digest=str(entry.get("digest", "")),
                    size=int(entry.get("size", 0) or 0),
                )
        return result

    def _get(self, path: str) -> dict:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as error:
            raise OllamaError(f"spike server unreachable: {error}") from error
        if response.status_code != 200:
            raise OllamaError(f"spike server {path}: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise OllamaError(f"spike server {path}: response was not JSON") from error
        if not isinstance(body, dict):
            raise OllamaError(f"spike server {path}: unexpected response")
        return body
