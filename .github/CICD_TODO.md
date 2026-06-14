# CI/CD Backlog

## Tier 0 — Formatting auto-fix pattern

Current behavior: black/isort/cargo fmt run as blocking checks. If they fail, the developer
must fix locally and re-push. That's correct — do not auto-commit from CI.

Desired improvement: instead of failing cold, run the formatter first, then check `git diff`.
If dirty, print the diff and fail with instructions. This gives the developer the exact patch.

```yaml
- name: Rust formatting
  run: |
    cargo fmt --manifest-path execution/Cargo.toml
    if ! git diff --quiet; then
      echo "Run 'cargo fmt' locally and commit the result:"
      git diff
      exit 1
    fi
```

Same pattern for Python (black then isort, then git diff check).

## Tier 0 — Environment vs. logic failure distinction

Problem: if `pip install` or `apt-get` fails, the error looks identical to a code failure.

Fix: split setup steps from check steps. Setup steps fail fast with a clear label.
Check steps only run if setup succeeded (GitHub Actions `needs:` already does this per-job,
but within a job, order matters).

Rule: always install full `requirements.txt` before any pylint/import check — otherwise
import errors are environment failures masquerading as code failures.

## Tier 1 / Tier 2

Disabled in `.github/workflows/_disabled/`. Re-enable once RAG pipeline is stable
enough to pass its own integration tests. The RAG async refactor (Layer 2 context,
non-blocking annotation) is the prerequisite.

## Priority order

1. Tier 0 formatting auto-fix pattern (quick, low risk)
2. Tier 0 environment/logic separation cleanup
3. Re-enable Tier 1 after RAG refactor
4. Re-enable Tier 2 after chaos/scaling tests are wired up
