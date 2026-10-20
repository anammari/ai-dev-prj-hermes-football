# The agent team and how it works

This project is built mostly by agents, so the team is written down rather than implied. The point is not
to list tools; it is to say who may do what, what each hand-off produces, and where a human has to sign.

| Role | Who | Owns | May not |
| --- | --- | --- | --- |
| Owner | Ahmad Ammari (human) | The problem, the scope, the policy decisions (data egress, model choice), the final review of every pull request | — |
| Coding agent | DeepSeek Harness coding agent | One milestone branch at a time: plan, code, tests, docs, commits; asks before the first code change | Merge its own work, push to `main`, or make a policy decision |
| Independent reviewer | A separate agent, without the author's context | Adversarial review of a finished milestone, or an audit of labels and data the author produced | Edit the branch it reviews |
| Verifier (planned, M4) | `answer-verifier` subagent | Checks that an answer's every factual claim traces to a tool result or a note | Answer a user question itself |
| Human reviewers | Course peers | Score the project against the 12 criteria | — |

## The process

1. **Plan before code.** The owner states the milestone and its acceptance criteria. The coding agent reads
   `AGENTS.md` and the linked docs, then reports a plan. No code until the owner approves; the plan's prompt is
   versioned in `prompts/` when it shapes product behaviour.
2. **One branch, one milestone.** Work happens on a milestone branch in the single working copy; `main` receives
   merged work only. Commits are imperative, with the reason in the body.
3. **Evidence, not confidence.** A change lands with a test, a scan, or a run artifact. The author does not sign
   off their own work: an independent reviewer looks for the failure the author's tests cannot see, and the
   owner reviews the diff and the evidence.
4. **Decisions are recorded.** Expensive or contested choices go in `_docs/decisions/` with context, options,
   the decision and how it will be verified. `_docs/ai-usage-report.md` records what was delegated, reviewed,
   rejected and proven, in the same commit as the work.
5. **Hand-offs are files.** Plans, prompts, samples, result artifacts and review notes live in the repository, so
   the next agent can continue without a chat history. The owner signs policy changes explicitly; the clef
   cloud-egress decision is the current example.

## What the team does not do

No agent pushes to `main`, merges its own pull request, or changes the data policy. No agent receives secrets;
`.env` stays local and only `.env.example` is committed. Telegram input is untrusted and is treated as a
prompt-injection candidate by every role.
