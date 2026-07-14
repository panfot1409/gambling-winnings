# Milestone 3B — Independent Acceptance Audit Plan

Adversarial, read-first acceptance review of the completed M3B trust-boundary
closure. Claims are reconstructed from source, Git objects, immutable artifacts,
disposable failure-injection repositories, and independent calculation — never
trusted because they appear in the PR body, terminal audit, bug log, or tests.

**Discipline.** No new research, no new experiment, no gate/holdout access, no
merge/undraft/retarget/tag. A defect is fixed only after a failing test
reproduces it; if none is found, no production code changes. Run-001 financial
bytes must stay byte-identical (HARD STOP on drift = Class-D incident).

## A. Read-only preflight — results

| # | check | result |
| --- | --- | --- |
| 1 | path / branch / HEAD / clean | `claude/m3b-fractional-risk-engine`, clean tree, no stash |
| 2 | HEAD == `016368300d387d70a93c8658c2adecf7c5f0d226` | **yes** |
| 3 | local tip == remote tip | **yes** (`0163683`) |
| 8 | both sealed ledgers 0 bytes, `e3b0c442…855` | **yes** (git blob `e69de29b`, unchanged vs base) |
| 9 | registry lifecycle registered→started→completed, one id, no run-002 | **yes** |
| 10 | M3B immutable v1 hashes | registry `204e66d2…`, protocol `9c1e00ec…`, results `81f94fab…`, report `68501639…`, manifest `d91ac46e…` |
| 11 | M2B/M3A immutable artifacts unchanged vs base | **yes** — `git diff base..HEAD` touches nothing under `research/m2b` or `research/m3a` |
| 12 | no completion-intent / temp / backup / recovery residue | **yes** — none tracked or present |
| 13 | base SHA `b3c261b5…` is an ancestor of HEAD | **yes** |
| 14 | `base..HEAD` diff scope | M3B only: `src/eth_research/{fractional,+7 shared}`, `research/m3b`, `docs/M3B*`, `tests/test_{fractional,m3b}*` + version-bump-touched tests, `.github/workflows/m3b-replay.yml`, `pyproject.toml`, `uv.lock`, `README.md` |
| 7 | no tag contains freeze `2628440` / reg `3f66c77` / exec `b00aa3b` / head | **yes** — only old `v0.1.0`–`v0.3.0`, none contain M3B |

Shared (non-fractional) `src` deltas are small (82/-18 over `__init__.py`
version bump, `walkforward.py`, and four `development*`/`methodology_v2` helpers) —
code only, no immutable artifact; behavioral impact is checked in §M and via the
M3A-replay gate.

**GitHub-side items (4, 5, 6) — blocked this session.** The GitHub MCP token
expired mid-audit and this session is non-interactive, so PR #5/#4 live state and
the four final-head workflow-run conclusions cannot be re-queried here. Last known
(this session, pre-expiry): PR #5 open, draft, not merged, base
`claude/m3a-development-research-lab` (not retargeted). CI is re-verified
**exhaustively and locally** below (§Q) by running the exact commands the CI
`checks` job runs; the git preflight already proves local == remote at the head
the runs were triggered on.

## B. Acceptance baseline

Freeze hashes/sizes for every immutable + additive artifact and the frozen
provenance (E `2628440`, R `3f66c77`, P `b00aa3b`; protocol/partition/dossier/
source-tree/bundle digests; the exact 75-cell grid). A single reviewed read-only
fixture/test verifies them — no casual hash duplication.

## C–L. Independent verification (adversarial)

- **C** Independent financial reconstruction of all 75 cells from committed inputs
  (not from the committed cells), via the deterministic replay + trace re-run and
  independent spot recomputation; exact identities, no generous tolerances.
- **D** Strict-model / JSON audit: every `from_json_bytes`, mechanical search for
  `str/int/float/bool/list/tuple` repair, and the full malformed-input attack set;
  prove valid run-001 bytes still round-trip byte-identically.
- **E** Accounting/solver red team with hand oracles (not line-for-line reimpl).
- **F** Engine causality + OHLCV/context/signal boundary red team, instrumented.
- **G** Completion-intent / crash-recovery state machine + crash-injection matrix.
- **H** Immutable archive-v2 independent attack matrix (registry is the anchor).
- **I** Execution-trace commitment independent oracle + mutation + cross-runtime.
- **J** Report-erratum completeness — independent enumeration of ALL 75 cells for
  cost-monotonicity inversions.
- **K** Sealed-partition firewall with layer spies; ledgers hashed before/after.
- **L** Prohibited-functionality + supply-chain audit (AST, not grep alone).

## M. Stacked-PR merge readiness

Simulate the PR#4→main merge and PR#5 retarget in a disposable clone only; write
the exact human-controlled merge/tag sequence. No outward-facing operation.

## N. Independent auditors

Three read-only subagents (accounting/solver/compat; causality/validation/risk/
liquidity/sealed; recovery/publication/archive/trace/erratum/CI). Every reported
issue is personally reproduced, classified, regression-tested, minimally fixed,
proven run-001-neutral, and logged.

## Q. Final verification

`python --version`, `uv lock --check`, `ruff check .`, `ruff format --check .`,
`mypy src tests examples`, `pytest --durations=30`, `git diff --check`, plus
`replay --check`, `verify_run_archive --deep`, `recovery --status`,
`test_readiness`.

## R. Handoff + verdict

`docs/M3B_INDEPENDENT_ACCEPTANCE_AUDIT.md` with one verdict: ACCEPTED FOR HUMAN
REVIEW · REJECTED — REMEDIATION REQUIRED · HARD STOP — CLASS D INCIDENT.

## Absolute stop

No M3C, run-002, gate/holdout, promotion, tuning, merge/undraft/retarget, tag,
branch deletion, or history rewrite. PR #5 stays open and draft.
