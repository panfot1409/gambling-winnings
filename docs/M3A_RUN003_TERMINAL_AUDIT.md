# Milestone 3A — run-003 terminal-completion audit (read-only handoff)

The final read-only audit of the run-003 terminal-completion milestone. It
records exactly what changed after the closure checkpoint, proves the sealed
invariants held throughout, shows that the corrective run-003 was registered,
executed once, and published with financials bit-identical to run-002, and
names the absolute stop. Nothing here authorizes any development-gate or
final-holdout access.

## 1. Starting SHA, final SHA, branch, PR

- Closure checkpoint (start): `18de74334723c37f49bc7a0ab10d152430716930`
- Final HEAD: `b4e90726b26d69f94e40ad76e7c9675dea11ed32`
- Branch: `claude/m3a-development-research-lab`
- PR: **#4 open and draft** — not merged, not undrafted.

## 2. Commit-identity model (N8)

Four distinct commits, recorded in distinct fields — never one field overloaded:

| role | commit | meaning |
| --- | --- | --- |
| `E` execution source | `b27f5d9c84d378d69ab31b0fcfda388af6b3698e` | final code/methodology before registration; the source tree that ran |
| `methodology freeze` | `bc51fffdfe497cce9b0c707d20fb61e0e462d7bd` | last commit touching the v2 methodology/protocol artifact |
| `R` registration container | `082b452123ee2a728ceb612aa08bb1599af621ff` | the registry-only commit that appended run-003's `registered` line (12A) |
| `run_head` | `cd868e8c1cfee3b92aa67db12e71b131dca4bba3` | clean HEAD at which the run executed (12B) |
| `P` run outputs | `e83c048c89dad45590850382b9cc952d268469e8` | the `started`/`completed` lines + the immutable run-003 body |

The registered/started/completed events record `execution_code_commit_sha = E`
and `registered_code_commit_sha = methodology freeze`; the results v2 body
records `execution_source_commit_sha = E`, `run_head_commit_sha = run_head`, and
`methodology_freeze_commit_sha = methodology freeze`.

## 3. Source identity held from E through the run

- `git diff b27f5d9 cd868e8 -- src/eth_research` is **empty**: the source tree
  that ran is byte-identical to the one `E` fingerprinted. The two commits
  between `R` and `run_head` (`2714d91`, `cd868e8`) touched only tests and the
  registry, never `src/eth_research`, so the recorded execution source faithfully
  identifies the code that computed run-003.
- `git diff b27f5d9 082b452` (`E..R`) is **exactly one inserted registry line**
  — no source, test, workflow, or methodology change accompanies the
  registration.

## 4. Registry-prefix SHA before/after

The six-line v1 prefix (run-001 r/s/c + run-002 r/s/c) is byte-for-byte
unchanged: `7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67`.
The registry now holds **nine** non-empty lines — the frozen six plus run-003's
`registered`/`started`/`completed`, appended after the prefix and chained by
`previous_event_sha256`.

## 5. Both access ledgers stayed byte-empty

`research/m3a/development_gate_access.jsonl` and
`research/m2b/test_evaluations.jsonl` are each **0 bytes**, hashing to
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. No
development-gate or final-holdout access ever occurred; run-003 read only the
research-train partition.

## 6. New defects N1–N10 corrected (failing-test-first)

Found in the closure checkpoint `18de743`; several were over-claimed as fixed
there. Each regression test failed on `18de743` before its fix. Full detail and
reproductions: `M3A_BUG_LOG.md`, `tests/test_m3a_terminal_defects.py`.

| id | defect (one line) | fix commit |
| --- | --- | --- |
| N1 | privileged boundary trusted an importable token, not the registry | `84036cc` |
| N2 | `publish_batch` could write outside the root via `..` | `a4bd46a` |
| N3 | non-unique, truncating temp filenames could clobber | `a4bd46a` |
| N4 | verification ran after publish, outside rollback scope | `a4bd46a` |
| N5 | rollback lacked durable fsync / unique temps / catastrophe state | `a4bd46a` |
| N6 | the promised calculation-free recovery finalizer did not exist | `1972715` |
| N7 | hierarchical interval recorded seed 20260713 while PCG64 used 20260714 | `76da0e6` |
| N8 | one commit field overloaded run-head with the registration commit | `44331d2` |
| N9 | no test exercised a successful end-to-end orchestration | `f06eddc`, `510e139` |
| N10 | workflows still piped `curl … \| sh`; the R7 test passed because of it | `436bd70` |

## 7. run-003 identity and correction scope

- id: `m3a-fixed-baseline-comparison-v2-run-003`, family
  `m3a-fixed-baseline-comparison-v2`.
- corrects: `m3a-fixed-baseline-comparison-v1-run-002`; `correction_kind =
  methodology_and_publication_governance`.
- `methodology_id = walk-forward-fold-stratified-bootstrap-v2`.
- The corrective run changed **inference method, provenance, and publication
  governance only** — not the walk-forward protocol, the partition, the
  strategies, the costs, or any financial parameter.

## 8. Registration → execution sequence actually followed

1. **Checkpoint E** — all code/workflow/test/recovery/replay/doc changes landed
   and green on CI (§6 fixes; dual-state replay set up).
2. **12A (`R`)** — `m3a_register --append` appended exactly one `registered`
   line; committed registry-only (`082b452`), pushed, CI-green, ledgers still
   zero.
3. **12B (`P`)** — `develop_m3a --run-experiment …` executed once on the frozen
   CPython 3.12.3 runtime: the orchestrator appended `started` before the first
   real call, evaluated the research train, published the immutable v2 archive
   transactionally, read it back / reconciled, then appended `completed`; the v2
   compatibility aliases were migrated. Committed as `e83c048`.

## 9. Financial equivalence — bit-identical to run-002

`eth_research.financial_equivalence.assert_financial_equivalence` over the
committed artifacts confirms every financial value is identical between run-002
(v1 archive) and run-003: **60** fold cells, **12** independent-fold summaries,
**12** pooled reset-OOS summaries, **12** full-train exploratory summaries, plus
the dataset content fingerprint. Only the bootstrap interval resampling,
provenance fields, and dependent report text changed. Standing proof:
`tests/test_m3a_run003_redteam.py::TestCommittedRun003FinancialEquivalence`.

## 10. Bootstrap change, reported without cherry-picking

- Primary corrected `fold-stratified-moving-block-bootstrap-v2` (blocks strictly
  within a fold; effective seed 20260713) is **narrower** than v1 in every one of
  the nine cells — removing seam-crossing blocks removes spurious cross-fold
  variance.
- The one qualitative change: the v2 primary `cash` interval marginally
  **excludes** zero, on the **negative** (underperformance) side (upper bound
  ≈ −0.0012%). This is the opposite of alpha and promotes nothing.
- The hierarchical sensitivity (`hierarchical-fold-block-bootstrap-v1`, effective
  seed 20260714 = base+1, the N7 fix) is the widest everywhere and straddles zero
  for every strategy, including `cash`.
- Full-precision record: `M3A_RUN003_BOOTSTRAP_COMPARISON.md`. Method rationale:
  `M3A_BOOTSTRAP_METHOD_NOTE.md`.

## 11. Immutable archive — three experiments, all verified

`verify_experiment_archive('.')` returns `(run-001, run-002, run-003)` and binds
each completed registry event to its archived bytes:

- run-001: recovered from history (results `b8616248…`, report `9362c631…`).
- run-002: originally present (results `dc4564fe…`, report `34baa74c…`).
- run-003: originally present, position 9 (results `5f6377b6…`, report
  `d6e92076…`, plus `return_evidence.json` and `artifact_manifest.json`).

The index lists exactly these three; regression:
`tests/test_experiment_archive.py`.

## 12. Terminal event binds the committed bytes

run-003's `completed` event pins `results_json_sha256 = 5f6377b6…`,
`report_markdown_sha256 = d6e92076…`, `result_bundle_sha256 = 8a0d4efe…`, and
`return_evidence_sha256 = b593a03c…`; the committed compatibility aliases hash to
the same values, and the aliases are byte-identical to the immutable archive.

## 13. Reproducibility (dual-state v2 replay)

`develop_m3a --check` dispatches on the latest completed schema: for run-003 (v2)
`verify_v2_replay` regenerates the immutable v2 archive from the committed raw
bytes and the recorded commit identities and byte-compares the aliases and the
archive, returning the run id. `verify_m3a_registry.py` re-validates the registry
lifecycle for all three experiments. Both pass in State A (run-003 registered
only) and State B (run-003 completed); regressions in
`tests/test_replay_m3a_v2.py` and `tests/test_m3a_orchestrator_e2e.py`.

## 14. Publication transaction + crash recovery (N2–N6)

Publication is an explicit `prepare → replace_all → verify → commit` transaction:
safe-root path resolution, `O_EXCL` unique temps, prior-byte retention until the
verify callback passes, marker-last ordering, directory fsync, and a fsynced
reverse rollback with a distinct catastrophic state. A durable
`completion_intent.json` carries the exact `completed` event bytes;
`m3a_recovery --status/--finalize` can append that event after re-verifying every
artifact, touching no strategy/engine/metric/bootstrap/ledger. Coverage:
`tests/test_publication.py`, `tests/test_m3a_terminal_defects.py`,
`tests/test_m3a_recovery.py`.

## 15. CI supply chain (N10/R7)

No surviving workflow pipes downloaded bytes into a shell; `uv==0.8.17` installs
from the hash-pinned PyPI wheel (`ci/uv-requirements.txt`, `--require-hashes`).
`uses:` are full-SHA pinned, `contents: read`, no secrets / `id-token` / writes,
host-allowlisted. Coverage: `tests/test_workflow_security.py`.

## 16. Successful end-to-end orchestration (N9)

`tests/test_m3a_orchestrator_e2e.py` drives the production lifecycle in a
disposable `git clone --local` carrying the full real M2B+M3A layer: it registers
run-003 with the production CLI, commits the registry-only `R`, and runs
`develop_m3a --run-experiment` via subprocess (consuming the id only in the
clone), asserting registered→started→completed, all three archives verifying,
State A/B replay + registry verifier, financial equivalence to run-002,
single-use refusal, and both ledgers byte-empty. Skip-guarded off the frozen
runtime and once run-003 is completed in the real repo.

## 17. Post-run adversarial verification (Section 19)

`tests/test_m3a_run003_redteam.py` adds standing, unconditional proofs on the
committed artifacts: real run-002↔run-003 financial equivalence; the aliases
mirror the immutable archive byte for byte; `verify_v2_replay` rejects a single
appended byte to either alias or the archive; the v1 registry prefix hashes to
the pinned digest; both ledgers are byte-empty.

## 18. Documentation refreshed (Section 21)

Updated to the terminal state: `research/m3a/README.md` (three experiments,
run-003 v2 aliases, corrected honest finding), the root `README.md` finding,
`M3A_BUG_LOG.md` (R5/R8 marked fixed with `e83c048`), `M3A_CLOSURE_AUDIT.md`
(final-HEAD correction `d1dbb68`→`18de743`, run-003-done note),
`M3A_CLOSURE_REMEDIATION.md`, `M3A_BOOTSTRAP_METHOD_NOTE.md`, and `M3A_PLAN.md`
(v2-correction pointers).

## 19. Terminal commit sequence (18de743 → HEAD)

`83c6414` plan → `a4bd46a` publication hardening (N2–N5) → `76da0e6` effective
seed (N7) → `436bd70` uv wheel (N10) → `44331d2`/`d463894` commit-identity split
(N8) → `84036cc` registry-verifiable context (N1) → `1972715` recovery finalizer
(N6) → `d66756b` bug-log backfill → `5fcff6c` registration CLI → `f06eddc`/
`bbb4f39` end-to-end + equivalence (N9) → `510e139` dual-state replay → `b5394d7`
bug-log → `f52cde1` register guards → `b27f5d9` freeze-runtime gate (**E**) →
`082b452` **12A registration (R)** → `2714d91`/`cd868e8` post-12A test fixes
(**run_head**) → `e83c048` **12B run outputs (P)** → `e804dfb` bootstrap record →
`3bebf10` State-B test adaptation → `b4e9072` post-run red-team.

## 20. Explicit non-goal confirmations

- The development gate was **never** evaluated; the final holdout was **never**
  evaluated; no row after 2022-06-21 UTC reached any strategy/backtest/metric/
  bootstrap (firewall spies in `tests/test_development_evaluation.py`).
- Neither sealed access ledger was appended to; both remain byte-empty.
- No candidate promoted (SMA/Donchian/any). No gate/holdout authorization
  constructed. No financial parameter changed. Nothing tuned after seeing output.
- No optimization/grids/ML/live/paper/exchange auth/wallets/signing/leverage/
  shorting/fractional exposure added.
- The six registry prefix lines were not rewritten; no experiment id reused; no
  history amended/rebased/squashed/force-pushed.
- PR #4 remains **draft** — not merged, not undrafted. No `v0.4.0` tag created.
  The branch was not deleted.

## 21. Remaining limitations (unchanged by run-003)

Five folds are weak evidence; every interval is an in-sample research-train
diagnostic, not annualized and not a profitability proof. Independent fold resets
are a comparison device, not a compounding path. One venue, one instrument, one
daily dataset. Computational sealing of the forbidden partitions is an
operational Python control, not a cryptographic guarantee. Commits are unsigned
(no signing key is available) — an environment limitation, not history to
rewrite. The `v0.3.0` tag debt is unrelated.

## 22. Reproduce on a fresh clone

```bash
uv sync --locked --all-extras --python 3.12.3
uv run --no-sync python -m eth_research.develop_m3a --repo-root . --check
uv run --no-sync python .github/scripts/verify_m3a_registry.py
```

The first regenerates and byte-compares the run-003 v2 archive and aliases; the
second re-validates the registry lifecycle for all three experiments and its
binding to the published bytes. The `M3A Replay` workflow runs both on the
authoritative CPython 3.12.3 runtime and on Python 3.12 / 3.13 and asserts both
ledgers stay byte-empty.

## 23. Absolute final stop

run-003 is completed, committed, pushed, reproduced, and red-teamed; the sealed
invariants held throughout. Stop: do not spend the development gate, do not
evaluate the final holdout, do not promote a candidate, do not merge or undraft
PR #4, and do not create `v0.4.0`.
