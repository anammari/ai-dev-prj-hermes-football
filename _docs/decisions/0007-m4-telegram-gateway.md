# 0007 — The M4 Telegram gateway is our own thin client

- **Status:** Accepted (2026-10-22)
- **Milestone:** M4
- **Related:** `_docs/product-spec.md` F5, `_docs/decisions/0003-prompt-router.md`, `_docs/decisions/0006-routing-safety-gate.md`, `hermes/SOUL.md`

## Context

The architecture names the Nous Research Hermes Agent as the gateway. M4 has three constraints that
the third-party runtime does not satisfy by itself:

- the routing gate must run **before every tool call**, and every answered turn must record its route,
  source and confidence;
- the only signed-off cloud egress is the user message to `clef:cloud`; tool output and note text must
  stay local, so a second cloud model cannot paraphrase them;
- the Telegram bot must be testable without a bot token, and the retained stack has no Telegram token
  or Hermes Agent image yet.

The Nous Hermes Agent owns its own model and tool loop. Its own agent could call the MCP tools without
our gate, and its model provider would need a separate data-egress decision for tool output and notes.

## Options

1. **Run the Nous Hermes Agent image and point it at the MCP server.** It would need a model provider,
   a Telegram token, a data volume and a config; the gate could not be guaranteed before its tool
   calls, and a cloud model would receive tool results. Rejected for M4, not for ever.
2. **Build a web chat instead of Telegram.** Rejected: Telegram is the M4 interface in
   `_docs/scoping.md` §8 and the product brief.
3. **Ship a thin Telegram gateway in `agent/gateway` that implements SOUL.md and calls the MCP
   server.** Chosen.

## Decision

`agent/gateway` is the shipped M4 Telegram client. It:

- long-polls Telegram (no inbound port, no webhook);
- calls the production router once per message, applies the hard gate, then calls one MCP tool;
- composes the answer deterministically from the tool payload — no second model, so no tool output or
  note text leaves the machine;
- writes one `agent_turns` row through the insert-only writer before sending;
- refuses every user outside `TELEGRAM_ALLOWED_USERS`, and runs health-only when no bot token is set;
- uses the same `hermes/SOUL.md` as the policy. `hermes/config.yaml` records the equivalent MCP
  surface for a future Nous Hermes Agent deployment; it is not read by the shipped gateway.

## Consequences

- Answers are clear and grounded but not conversational: the composer restates the tool result. A
  model-backed composer would need a local model and a new egress review.
- There is no multi-turn memory; each turn routes the message it receives. Clarify resolves one
  question, not a conversation. That is a known M4 limit, not a hidden one.
- The MCP surface stays the contract. A later Hermes Agent can replace the gateway without changing a
  tool, a test or a note.

## Verification

- Unit: `tests/test_gateway.py` (composer, one-tool pipeline, allowlist, commands, health).
- Integration: `tests/integration/test_gateway_stack.py` exercises a database question, a notes
  question, an instruction override, a scorer refusal and a vague question against the real router,
  MCP server, corpus and writer role.
- Manual: `make ask Q="where are Arsenal in the table?"` and a rules question; Telegram smoke test is
  the owner's step after setting a bot token (guide in `_docs/m4-guide.md`).
