# Scan output

`latest/` and `ci/` are generated. Raw reports are not committed: they are large, they age, and a
report can quote the line a scanner matched. CI uploads them as artifacts; a review records the
counts and the exceptions in `../<date>-baseline.md`.

```bash
make scan-secrets   # gitleaks, working tree, redacted JSON report
make scan-deps      # pip-audit + pnpm audit --prod
make scan-images    # trivy over the built images (needs the host Docker socket)
```

A scan that fails is a finding, not a flake: fix the dependency, rotate the secret, or record the
accepted advisory in the baseline file with the date it is reviewed again.
