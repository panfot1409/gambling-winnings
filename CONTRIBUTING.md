# Contributing to eth-research

Thanks for your interest. This project is a **research-only, offline** toolkit, and contributions are
welcome within that boundary. Please read this before opening a pull request.

## The boundary (non-negotiable)

Contributions that add any of the following will be **declined on scope**, regardless of quality:

- network access, exchange/broker connectivity, API authentication, or a general HTTP client in the
  runtime package;
- wallet integration, key handling, signing, or order routing;
- leverage, margin, shorting, or derivatives;
- dynamic code loading (`eval`/`exec`/plugin import) in the runtime;
- an optimizer/grid/Bayesian/genetic/ML search over the data;
- any use of an accepted real dataset for a governed experiment outside the existing protocol.

These are enforced by tests (an import-closure firewall, a distribution scanner, and governance
checks). The narrow surface *is* the product.

## Development setup

```bash
uv sync --locked --all-extras        # exact locked env CI uses (recommended)
# or: python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Requires Python 3.12+.

## Gates every change must pass

Run the full local battery before pushing — CI runs the same on 3.12 and 3.13:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy                    # strict, over src/ tests/ examples/
uv run pytest -q               # add -m 'not slow' to skip the fractional grid while iterating
```

All four must pass. New behavior needs a test; a bug fix should come with a **failing-test-first**
regression that fails on the pre-fix code.

## Determinism & reproducibility

Artifacts are canonical JSON (sorted keys, fixed indent, trailing newline) with domain-separated
SHA-256 identities. Do not introduce wall-clock, `Math.random`-style nondeterminism, locale
dependence, or set-ordering into anything that feeds an identity. The registration verifiers fail
closed on drift — if you change a public surface, regenerate the pinned snapshot in the same PR.

## Governance invariants

The three sealed access ledgers under `research/` stay **byte-empty**, and no accepted artifact under
`research/mXX` may change. If your work seems to require touching one, stop and open an issue first.

## Pull requests

- Keep PRs focused; describe what changed and why, and how you verified it.
- Reference any issue it closes.
- Be kind and precise in review (see `CODE_OF_CONDUCT.md`).

## License note

The repository currently ships **no `LICENSE`** (see `docs/V1_LICENSE_DECISION.md`). Until a license
is chosen by the maintainers, by contributing you are proposing changes to the maintainers' own
repository; redistribution terms for the project as a whole remain the maintainers' decision.

## Audit and review boundaries (read-only by default)

Independent auditors — human or automated — are **read-only with respect to the
shared working tree**. This is a correctness requirement, not etiquette: a writer
in a shared checkout invalidates every concurrent reader, and this repository has
already lost two full-suite runs and produced one torn import block that way (see
`docs/V2E_BUG_LOG.md`, process defect P-1).

When auditing or red-teaming:

- do not modify, create, delete, format or patch any file in the shared checkout;
- do not run `git` commands that write (`commit`, `add`, `checkout`, `merge`,
  `reset`, `rebase`, `push`) — reading history is expected and encouraged;
- never invoke a build/registration command with `--write` against the shared tree;
- reproduce every attack in a scratch directory or a disposable clone, and say
  in your report where you worked;
- if you believe a source change is required, report it — do not apply it.

A finding is stronger, not weaker, for having been produced without touching the
thing under audit: it cannot be confused with the auditor's own edits.

Correspondingly, whoever holds the write role must not run `git add -A` while any
audit or background task is live; stage explicit paths, and if another task's
work is swept in by mistake, say so in the commit rather than letting the message
misdescribe the contents.
