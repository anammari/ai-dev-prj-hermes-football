# The agent team

The project is built mostly by agents, so the roles are explicit.

| Role | Who | Owns | May not |
| --- | --- | --- | --- |
| Owner | Ahmad Ammari | Scope, policy (egress, model), final PR review | — |
| Coding agent | DeepSeek Harness | Plan, code, tests, docs, commits on one branch | Merge own work, push to main, decide policy |
| Independent reviewer | Separate agent, no author context | Adversarial review of a milestone, label/data audit | Edit the branch under review |
| On-call agent | `oncall` container (`agent/oncall`) | Alert evaluation, daily data-quality digest, eval-age check | Write the database, read message text, call a model or upstream, answer users |
| Verifier (deterministic) | `agent/oncall` digest checks | Check that recent answers carry a timestamp or `Source:`; report the rate | Judge prose or re-answer the question |
| Human reviewers | Course peers | Score the 12 criteria | — |

## Process

1. **Plan before code.** Owner states the milestone and acceptance criteria; agent reads the docs and reports a plan.
   Prompts that shape behaviour go in `prompts/`.
2. **One branch, one milestone.** All work in the single root checkout; `main` only receives merged work. Imperative
   commits, reason in the body.
3. **Evidence, not confidence.** Every change lands with a test, scan or run artifact. The author does not sign off
   their own work; an independent reviewer looks for what the tests miss.
4. **Decisions are recorded.** Expensive/contested choices go in `decisions/`; AI usage in `ai-usage-report.md` in
   the same commit.
5. **Hand-offs are files.** Plans, prompts, samples and results live in the repo, not in chat.

No agent merges its own PR, pushes to `main`, or changes data policy. No agent receives secrets. Telegram input is
always untrusted.
