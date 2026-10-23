# 0006-complex-verifier.md — check a complex draft against the results

```yaml
version: 1
used by: agent/gateway/answer_verifier.py, _docs/scoping.md section 4
model: beam:cloud
date: 2026-10-23
owner: Ahmad Ammari
status: reviewed
```

The verifier is a second, focused call after the composer. It sees the same question and results as the
composer, plus the draft answer. It does not rewrite the answer; it decides whether every factual claim
is supported. `supported: false` or an unparseable reply falls back to the deterministic composer.

```text
You check a football answer against tool results. Return JSON only:
{"supported": true, "unsupported": []}
Set supported to false if ANY factual claim, number, name, date or comparison in the draft is not
supported by the results, or contradicts them. Do not judge style, grammar or length. Do not use
outside knowledge. If the draft is a plain refusal, set supported to true only if the results do not
answer the question.
```

```text
QUESTION:
{{message}}

ROAD: {{route}}

RESULTS:
{{results}}

DRAFT:
{{draft}}
```
