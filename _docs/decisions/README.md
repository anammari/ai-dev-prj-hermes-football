# Decision records

One short file per decision a future contributor should not have to re-litigate. Write one when a choice is expensive
to reverse, when two documents disagreed, or when a reviewer asks "why is it like this?".

- [0001 — The notes corpus: Markdown files, a manifest, and an index](0001-notes-corpus-manifest.md)
- [0002 — Embedding model: embeddinggemma-2:270m, local, 768 dimensions](0002-embedding-model.md) *(superseded by 0004)*
- [0003 — How the bot chooses between the database and the notes (router spike)](0003-prompt-router.md)
- [0004 — Embedding tag: embeddinggemma:300m, because the `-2` tag needs MLX](0004-embedding-tag-mlx.md)

Format: Status, Milestone, Related, Context, Decision, Alternatives, Consequences, Verification. Keep it under a page.
A decision that changes gets a new record that supersedes the old one; old records are not edited into agreement with
the present.
