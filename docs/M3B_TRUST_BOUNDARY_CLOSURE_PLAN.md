# Milestone 3B — Trust-Boundary Closure Plan

Strict domain models · validated engine boundaries · durable completion recovery ·
true immutable run archive · execution-trace commitments · append-only report
erratum · adversarial audit.

This is a **closure / hardening** milestone, not new research. It closes
engineering and provenance weaknesses in Milestone 3B **without changing any
published run-001 financial result**, without rerunning the experiment, and
without touching the development gate or final holdout.

## 0. Starting state (read-only preflight, verified)

| item | value |
| --- | --- |
| branch | `claude/m3b-fractional-risk-engine` |
| starting HEAD | `f2269045a794d35ba1a7b3c8570cac1b03f1932b` (local == remote) |
| PR base | `claude/m3a-development-research-lab` (PR #5, open, **draft**) |
| freeze E / register R / execute P | `2628440` / `3f66c77` / `b00aa3b` |
| experiment id | `m3b-fractional-execution-risk-v1-run-001` (one; registered→started→completed) |
| sealed ledgers | `research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl` — both 0 bytes, `e3b0c442…855` |
| results / report / manifest sha256 | `81f94fab…` / `68501639…` / `d91ac46e…` |
| registry / protocol sha256 | `204e66d2…` / `9c1e00ec…` |
| bundle sha256 | `c4ed0b6d…` |
| m2b / m3a drift vs base | 0 files |
| baseline gates | `uv lock --check`, `ruff`, `mypy(fractional)` all clean |

Note: the milestone brief refers to `research/m3b/registry.jsonl`; the actual
committed registry is **`research/m3b/experiment_registry.jsonl`**. All work uses
the real path.

## 1. Absolute invariants (never violated)

These committed files are immutable — never edited, reserialized, or replaced;
only **additive** files beside them are allowed:

- `research/m3b/experiment_registry.jsonl`
- `research/m3b/fractional_protocol.json`
- `research/m3b/fractional_results.json`
- `research/m3b/fractional_report.md`
- `research/m3b/experiments/run-001/manifest.json`
- every M2B/M3A immutable artifact; both sealed ledgers.

**HARD STOPs** (preserve the branch, provide evidence, do not "repair"): replay
produces different financials; any immutable artifact changes one byte; either
ledger leaves 0 bytes; any code path reaches the gate/holdout; a validation fix
changes a valid run-001 calculation; a new experiment would be required;
recovery would need recomputation; history rewrite; unexplained cross-runtime
financial drift; a control needs secrets/credentials/network.

**Bit-identity gate.** After every change to accounting / solver / cost / risk /
liquidity / engine, `python -m eth_research.fractional.replay --check` must still
report `completed: results_reproduced, report_reproduced, archive_verified` and
the committed artifact hashes above must be unchanged. Validation only **rejects
invalid inputs**; it never alters a valid computation.

## 2. Defect table (reproduce-before-fix)

| id | defect (confirmed) | evidence | required invariant |
| --- | --- | --- | --- |
| R1 | post-publication crash has no durable, calculation-free recovery; a completion-append failure can append `failed` despite fully published valid artifacts | `orchestrator._run_and_publish` publishes then appends `completed`; the `except` appends `failed` | durable completion intent before publish; crash finalized without recomputation; a published exact bundle is never mislabeled `failed` |
| R2 | "immutable archive" is only `manifest.json` pointing at the mutable singleton paths | `experiments/run-001/` holds only `manifest.json`; manifest → `fractional_results.json`/`fractional_report.md` | additive per-run immutable-v2 archive; singletons stay byte-identical aliases; future runs use unique paths |
| R3 | manifest parser coerces types via `str(...)` | `archive.py:147-152` `str(payload[...])` | strict decode + delegate to constructor; reject wrong JSON types, non-finite, dup/unknown/missing keys, unsafe paths |
| R4 | results parser repairs input via `int()/float()/str()` (28 sites) | `results.py` `float(payload…)`, `int(payload…)`, `str(payload…)` | parser only decodes; no value repair; bool≠int; NaN/Inf/overflow rejected |
| R5 | invalid accounting values cross the boundary — no `__post_init__` on `Tolerances`/`PortfolioState`/`Fill`; `<`-comparisons let NaN pass | `accounting.py` classes have no validation | refuse non-finite/malformed state before any calculation; NaN never survives a `<` guard |
| R6 | invalid cost/risk/liquidity configs accepted (NaN participation, bool lookbacks, min_obs>lookback, non-UTC as_of, dup/unsorted history, non-finite coeffs) | partial guards in `cost_model`/`risk`/`liquidity` | strict config + history validation; refuse repair/sort |
| R7 | **public engine applies a signal positionally**, discarding its index | `engine.py:148` `target_positions(full).to_numpy(...)` | strict OHLCV/context/signal validation; a right-length wrong-index Series is **refused**, not applied |
| R8 | archive verifier does not fully verify the tree (rogue files, id/version substitution, symlink, traversal, alias divergence, forged-consistent copy) | `verify_published_run` checks hashes but not the on-disk tree | `verify_m3b_run_archive` enumerates the tree, forbids symlinks/traversal/unknown files, binds ids/paths |
| R9 | `started` and `completed` share one timestamp | registry `event_time_utc` equal on both | append-only legacy disclosure; future v2 requires distinct increasing clock reads; run-001 unchanged |
| R10 | immutable report overstates cost monotonicity (not limited to fold medians) | `fractional_report.md` §6 "shrink … monotonically" | append-only erratum; cellwise monotonicity is false (Donchian fold-1 base<stressed counterexample) |
| R11 | per-run "return evidence" is only the aggregate JSON; a reviewer cannot verify each cell's target/fills/costs/equity | only `fractional_results.json` exists | deterministic, size-bounded execution-trace commitments regenerable by replay |

## 3. Strict-validation policy (Section 3)

One shared module `src/eth_research/fractional/validation.py` with strict
helpers: `require_bool`, `require_int` (rejects `bool`), `require_nonnegative_int`,
`require_positive_int`, `require_real` (rejects `bool`), `require_finite_real`,
`require_nonnegative_real`, `require_positive_real`, `require_unit_interval`,
`require_nonempty_str`, `require_exact_string`, `require_hex64`,
`require_sha256_fingerprint`, `require_safe_relative_path`,
`require_utc_timestamp`, `require_tuple`, `require_exact_keys`,
`require_canonical_order`.

Rules: never `str()/int()/float()` to repair a parsed value; integer acceptance
is explicit (no silent int→float unless the contract says so); `bool` is neither
int nor real; all financial values finite; **constructor and parser share the
same invariant surface** (construct == parse); strict JSON via the existing
shared duplicate-key / non-finite decoder; valid run-001 bytes still serialize
identically; valid calculations stay bit-identical. Tolerances stay explicit and
documented — no broad `isclose` that could hide accounting drift.

## 4. Filesystem layout (additive only)

```
research/m3b/
  experiment_registry.jsonl          (immutable)
  fractional_protocol.json           (immutable)
  fractional_results.json            (immutable singleton alias)
  fractional_report.md               (immutable singleton alias)
  artifact_annotations.jsonl         (NEW: hash-chained non-research annotations)
  experiments/run-001/
    manifest.json                    (immutable)
    immutable-v2/                     (NEW, additive)
      fractional_results.json         (byte-identical copy)
      fractional_report.md            (byte-identical copy)
      execution_trace_commitments.json(NEW)
      archive_v2.json                 (NEW: binding graph)
  errata/
    m3b-run001-report-cost-monotonicity-v1.json  (NEW)
    m3b-run001-report-cost-monotonicity-v1.md    (NEW)
docs/  (NEW specs: recovery, archive-v2, execution-trace, strict-model, report-erratum, terminal-audit)
src/eth_research/fractional/  (NEW: validation.py, recovery.py, archive_v2.py,
    trace_commitments.py, errata.py, annotations.py, archive_verify.py, lifecycle_v2.py)
```

## 5. Recovery state machine (Section 6)

`CompletionIntent` (strict, fsynced before publish) binds registered/started
event hashes, code/protocol/partition/dossier/source/version, expected artifact
paths+hashes, expected bundle hash, and the exact `completed` event bytes/hash.

Execution order: verify preconditions → append `started` → calculate → assemble
all artifact + completed-event bytes in memory → validate/reconcile → **write+
fsync intent** → publish batch transactionally → readback+verify → append exact
`completed` → fsync registry+dir → remove intent+fsync.

Recovery (calculation-free; never calls a strategy/backtest/metric/dataset):

| state | action |
| --- | --- |
| no intent + no terminal event | ordinary incomplete `started` run |
| valid intent + exact published artifacts + no terminal | **finalize** (append exact `completed` from intent) |
| valid intent + no artifacts | rollback/cleanup allowed |
| valid intent + partial artifacts | finish from intent-staged bytes or roll back deterministically |
| valid intent + divergent artifacts | contamination → refuse |
| `completed` present | verify hashes; remove stale exact intent if safe |
| `failed` present | never rewrite to `completed` |

CLIs: `recovery --status` (read-only), `recovery --finalize <id>`. Failure
injection at every boundary. run-001 is **not** retrofitted; an append-only
legacy audit record states it predates intent-v2 but currently verifies.

## 6. Execution-trace commitment spec (Section 8)

`execution-trace-v1/sha256`: per-cell, deterministically replayed, canonical
record sequence over primitive per-bar state (timestamp ns, requested +
risk-adjusted target, prior cash/qty, reference open, lagged liquidity,
participation cap, requested/executed qty, fill classification, side, reference/
fill price, gross notional, fee, spread/slippage/impact components, cash/qty
after, close, marked equity, turnover contribution). Domain-separated hash;
`float.hex()`; negative-zero normalized; canonical nulls; cell identity + fold
bounds + strategy + scenario + record count included. Per-cell hashes fold into
an ordered fold/root hash bound in `archive_v2.json`. **Size decision first**:
estimate full/compressed/per-cell/per-fold/aggregate; commit the reconstructible
commitments (not raw traces) if full traces exceed a documented cap; replay is
the reconstruction mechanism. Never exposes gate/holdout; called deterministic
hash-bound evidence, **not** cryptographic attestation.

## 7. Test strategy (Section 13)

Focused tests after each change (`pytest -x -vv` on the failing file); external
timeout; no two concurrent full suites; at most two local full passes (post-
integration + final head). Groups: strict model/parser, accounting/solver/cost,
risk/liquidity, engine causality/input, archive, publication/recovery, trace,
erratum/annotation, hygiene, replay. Report any test > 30 s. The standing
M3A/M3B E2E rehearsals run separately so their duration is visible.

## 8. Commit plan (Section 14, append-only; no amend/squash/rebase/force-push)

1. this plan · 2. reproduce R1–R11 · 3. strict domain models ·
4. harden accounting/solver/cost/risk/liquidity · 5. strict engine boundary ·
6. completion-intent + state machine · 7. recovery + failure injection ·
8. immutable archive v2 + annotations · 9. execution-trace commitments ·
10. archive/provenance verifier · 11. report erratum + legacy disclosure ·
12. lifecycle/registry v2 (fixtures only) · 13. hygiene + replay CI ·
14. red team + fixes · 15. docs + PR body · 16. final read-only audit.

Push periodically; never leave a known CI-red terminal state unless the next
pushed commit fixes it and the interim is documented.

## 9. Hard stops (restated)

Any of: replay financial drift; immutable-byte change; ledger non-empty;
gate/holdout reach; a validation change altering a valid run-001 number; a
required new experiment; recovery needing recomputation; history rewrite;
cross-runtime drift; a control requiring secrets/credentials/network. On a hard
stop: **do not repair data**; preserve the branch; report with evidence.

## 10. Absolute final stop

Terminal state: a hardened, reproducible M3B measurement instrument with
unchanged run-001 financials and an honest append-only correction trail. No
M3C; no run-002; no gate/holdout; no candidate promotion; no strategy-parameter
change; PR #5 stays open+draft and stacked on PR #4; PR #4 untouched; no tag;
no branch deletion; no history rewrite. Next step is independent human review.
