# Security artifacts

What is here, what it is for, and what is generated rather than committed.

| File | Kind | Source of truth for |
| --- | --- | --- |
| [`capability-table.md`](capability-table.md) | committed policy | Every runtime capability, the identity it uses, and the thing it may not do. `AGENTS.md` rules 7 and 8. |
| [`threat-model.md`](threat-model.md) | committed policy | Assets, actors, trust boundaries and the threats this project accepts or mitigates. |
| [`scans/README.md`](scans/README.md) | committed policy | How the scans run locally and in CI, and what may be committed. |
| `scans/latest/` | generated | Raw scan output. Ignored by git; uploaded as CI artifacts. |
| `scans/<date>-baseline.md` | committed | A redacted snapshot with counts, tool versions and the review that followed. |

## Tools

| Tool | What it finds | Where it runs | Blocks a merge |
| --- | --- | --- | --- |
| `gitleaks` | secrets in the working tree (PR) and in history (nightly) | `make scan-secrets`, CI `security`, nightly | yes |
| `pip-audit` | known vulnerabilities in the Python environment | `make scan-deps`, CI `security`, nightly | yes |
| `pnpm audit --prod` | known vulnerabilities in the dashboard's production dependencies | `make scan-deps`, CI `security`, nightly | yes |
| `trivy fs` | vulnerable lockfiles and committed secrets | CI `security` | yes |
| `trivy image` | vulnerable OS/package layers in the built images | `make scan-images`, nightly | no (main/nightly) |
| `actionlint` | workflow syntax and expression mistakes | `make lint-workflows`, CI `lint` | yes |
| Dependabot | dependency drift, as pull requests | GitHub | no (owner decides) |

`make security-scan` is the local pair: secret scan plus dependency audit. It reads the repository and
the public advisory databases; it does not send source, prompts or data to a project service. The
image scans need the Docker socket **on the host**, not inside a project container; no Compose service
has that mount.

## What is committed

- this policy, the capability table, the threat model;
- `.gitleaks.toml` with a narrow allowlist for placeholders and test literals;
- a redacted baseline summary per review, so a reader can see what the tools said without a growing
  directory of raw JSON.

## What is generated

- `security/scans/latest/*.json` locally and `security/scans/ci/*` in CI; ignored;
- CI uploads the raw reports as artifacts;
- no scan report is a runtime dependency and nothing in the app reads this directory.

## Thresholds and exceptions

- `pip-audit` and `pnpm audit --audit-level high` fail the job on a known vulnerable production
  dependency;
- `trivy` fails on `HIGH`/`CRITICAL`;
- an accepted advisory is recorded in `scans/<date>-baseline.md` with the package, the advisory id, why
  it cannot be fixed now, and the date it is reviewed again. A silent allowlist entry is not accepted.
