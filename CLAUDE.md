# CLAUDE.md — working notes for Claude Code

The project rules are in [`AGENTS.md`](AGENTS.md). Read that first: one working copy, work on a milestone
branch, never commit on `main`, no self-merge, no secrets, tests before a push.

This file adds the operational rule that is easy to forget after a milestone lands.

## Post-milestone Docker cleanup (required)

Run this after the **final** build of the milestone, before the final commit and push. Do not wait for the owner
to ask for it.

1. **Recreate services on stale images first.** Run `docker ps --format '{{.Names}} {{.Image}}'`; a container
   showing `<none>` or an image ID is running a replaced image. `docker compose up -d --force-recreate <service>`
   so it runs the current tag. Never delete an image that a running container uses.
2. **Remove dangling images.** `docker image prune -f`. Report the reclaimed size. `prune` removes images with no
   tag and no child; an image shown as `repo/name:<none>` is digest-only, is not dangling, and is not removed.
3. **Prune the build cache.** `docker builder prune -f`. The next build is slower; that is the trade.
4. **Check volumes.** `docker volume ls -f dangling=true` and `docker system df -v`. Both project volumes
   (`hermes-football_pgdata`, `hermes-football_ollama-data`) hold real state and must never be removed as part
   of cleanup. Dangling volumes are reported, not deleted, unless the owner explicitly confirms.
5. **Remove known superseded tagged images** only when no container uses them and the replacement is already
   built (for example the old `ollama/ollama:0.40.2` after the local Ollama image exists). Ask before deleting
   third-party images that are not part of this project.
6. **Never run `docker system prune -a --volumes`.** It removes data volumes and images other projects use.
7. **Verify the stack afterwards.** `docker compose ps` must show the expected services; `hermes`, `backend`,
   `ollama`, `mcp-server` and `db` must be healthy. Check the gateway with:
   `docker compose exec -T hermes python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8200/health').read().decode())"`.
8. **Report the before/after** of `docker system df` in the final message, with what was removed and what was
   deliberately kept.

## Review requests

Never request a Copilot review. Do not use `gh pr edit --add-reviewer`, do not call the review-request API, and do
not comment `@copilot review`. The owner decides whether Copilot reviews a pull request and requests it manually.
This applies to every coding agent working in this repository.
