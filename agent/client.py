"""The decision-model client: one POST to Ollama's `/v1/systemone`.

Only the routing request goes here. The base URL is the signed-in host Ollama (`clef:cloud` runs in
Ollama's cloud), configured through `ROUTER_BASE_URL`. The response is parsed strictly: a missing
choice, a non-numeric confidence or an unknown shape is an error, and the router turns that error into
a fallback refusal rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class DecisionError(RuntimeError):
    """The decision endpoint is unreachable, missing the model, or answered with an unexpected shape."""


@dataclass(frozen=True)
class Answer:
    label: str
    confidence: float
    probabilities: dict[str, float]


class DecisionClient:
    def __init__(self, base_url: str, model: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> DecisionClient:
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
            raise DecisionError(f"{self.model}: request failed: {error}") from error
        if response.status_code != 200:
            raise DecisionError(f"{self.model}: HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as error:
            raise DecisionError(f"{self.model}: response was not JSON") from error
        if not isinstance(body, dict):
            raise DecisionError(f"{self.model}: response is not a JSON object")
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise DecisionError(f"{self.model}: response has no answers object")

        parsed: dict[str, Answer] = {}
        for name in questions:
            entry = answers.get(name)
            if not isinstance(entry, dict) or "choice" not in entry:
                raise DecisionError(f"{self.model}: no choice for question {name!r}")
            probabilities = entry.get("probabilities") or {}
            if not isinstance(probabilities, dict):
                raise DecisionError(f"{self.model}: probabilities for {name!r} are not an object")
            try:
                confidence = float(entry.get("confidence", 0.0))
                parsed_probabilities = {str(key): float(value) for key, value in probabilities.items()}
            except (TypeError, ValueError) as error:
                raise DecisionError(f"{self.model}: malformed number for {name!r}") from error
            parsed[name] = Answer(
                label=str(entry["choice"]),
                confidence=max(0.0, min(1.0, confidence)),
                probabilities=parsed_probabilities,
            )
        return parsed
