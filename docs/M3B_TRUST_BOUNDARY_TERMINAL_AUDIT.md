# Milestone 3B — Trust-Boundary Closure: terminal audit & handoff

This is the terminal, read-only audit record for the M3B trust-boundary closure.
It is a **hardening/closure** milestone: it closed engineering and provenance
weaknesses in the published run-001 **without changing any financial result**,
without re-running the experiment, and without touching the development gate or
final holdout. The next step is independent review — nothing here promotes a
candidate, opens M3C, or runs a new experiment.

## What was closed (R1–R11)

Every defect was reproduced (as a failing test or an enumerated fact) before it
was fixed. See `docs/M3B_BUG_LOG.md` for the full table; in brief:

- **R1** — durable `CompletionIntent` + calculation-free `recovery` finalizer; the
  orchestrator's failure path can no longer mislabel a published success as `failed`.
- **R2** — a genuine per-run immutable body (`immutable-v2/` byte-identical copies
  + `archive_v2.json`), registry-anchored.
- **R3/R4** — strict parsers that decode and never repair (`str()/int()/float()`
  coercion removed; `bool`/NaN/Inf rejected).
- **R5/R6** — finiteness/bool/int guards across accounting, cost, risk, liquidity.
- **R7** — the public engine validates the signal index, OHLCV canonicality,
  context contiguity before use.
- **R8** — `verify_m3b_run_archive`, a 24-point (25 with `--deep`) aggregate verifier.
- **R9** — documented run-001's identical lifecycle timestamps as a legacy artifact;
  lifecycle-v2 fixtures prove distinct timestamps are supported.
- **R10** — an append-only report erratum with the complete full-precision cell-wise
  counterexample to the overbroad cost-monotonicity claim.
- **R11** — size-bounded, replay-reconstructible per-cell execution-trace commitments.

## Invariants held throughout (verified after every commit)

- `python -m eth_research.fractional.replay --repo-root . --check` →
  `completed: ledgers_byte_empty, results_reproduced, report_reproduced, archive_verified`.
  The results / report / manifest bytes and the registry lifecycle are unchanged.
- Both sealed access ledgers (`research/m3a/development_gate_access.jsonl`,
  `research/m2b/test_evaluations.jsonl`) stay **byte-empty** (`e3b0c442…855`): the
  development gate and final holdout were never evaluated.
- Every closure artifact is additive; no committed run-001 byte was modified.
- PR #5 stays **open and draft**, stacked on `claude/m3a-development-research-lab`;
  no merge, retarget, rebase, force-push, or tag. The M2B/M3A immutable artifacts
  are untouched.

## Independent adversarial audit (3 read-only passes)

Three independent auditors reviewed the closure (recovery/R1;
archive-v2/trace/annotations; erratum/verifier/strict-validation). None found an
exploitable defect in the financial results, the crash-recovery core, or the R10
counterexample-completeness invariant. One MEDIUM and several LOW verifier-strength
/ hygiene gaps were surfaced; all genuine ones are fixed and regression-tested, and
two inherent append-only-log / shared-helper properties are documented as accepted.
See the "Closure red team" table in `docs/M3B_BUG_LOG.md`.

## One command to re-verify everything

```
python -m eth_research.fractional.replay --repo-root . --check
python -m eth_research.fractional.verify_run_archive --repo-root . --deep
python -m eth_research.fractional.recovery --repo-root . --status   # -> no-intent
```

`M3B Replay` CI runs the dual-state replay + the deep run-archive verification on
CPython 3.12.3 and the 3.12/3.13 compatibility matrix.

## Absolute final stop

No M3C, no run-002, no development-gate or final-holdout evaluation, no candidate
promotion, no strategy-parameter change. PR #5 remains open and draft. No tag,
branch deletion, or history rewrite. The next step is **independent review**.
