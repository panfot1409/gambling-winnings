# Milestone 3D — Prospective Evidence Governance, Adaptive-Overfitting Firewall, and Future-Only Data Facility

This document preregisters Milestone 3D **before** any implementation, version
bump, model, ledger, acquisition, or workflow is written. It is committed alone
as the first M3D commit. Everything M3D does must conform to what is written
here; any deviation is a defect to be corrected, not a silent change.

M3D is **data-only and governance-only**. It does not create, evaluate, rank,
tune, promote, or report performance for any strategy. Its scientific outcome is
deliberately uneventful:

> A prospective dataset and governance facility now exists, but it is immature
> and no strategy has been evaluated on it.

No alpha claim. No candidate. No test result. No promotion.

---

## 1. Upstream state this milestone builds on (verified read-only)

The non-negotiable read-only preflight (§0 of the assignment) ran before this
document was written and was **fully clean**:

| Fact | Verified value |
| --- | --- |
| Upstream M3C branch | `claude/m3c-adaptive-research-governance` |
| M3C accepted head | `c50872431534f199dd0ba78ef86967bcd0b94e4c` |
| Base `main` (merge-base = main tip) | `a7640e35c861e72413c9a0154e2ae3af0a075889` |
| PR #6 | open · draft · unmerged · base `main` · head `c508724` |
| CI run 29409840531 | success (all jobs) |
| M2B Replay 29409840514 | success (all jobs) |
| M3A Replay 29409840524 | success (all jobs) |
| M3B Replay 29409840589 | success (all jobs) |
| M3C Replay 29409840518 | success (all jobs) |
| Worktree | clean; local == remote |
| Package version | `0.6.0` |
| M2B/M3A/M3B/M3C replays | all reproduce |
| M3C deep archive | 15 checks pass |
| M3C recovery | no-intent |
| M3C lifecycle | `registered → started → completed` (one experiment id, no run-002) |
| M3C terminal decision | `rejected_for_development_gate_promotion` |
| Development-gate ledger `research/m3a/development_gate_access.jsonl` | tracked, 0 bytes, sha256 `e3b0c442…855` |
| Final-holdout ledger `research/m2b/test_evaluations.jsonl` | tracked, 0 bytes, sha256 `e3b0c442…855` |
| M2B canonical dataset | 3702 rows; first open `2016-05-23T00:00:00Z`; last open `2026-07-11T00:00:00Z`; content fingerprint `sha256:273f89eb07ae882784e40c2bc2ef2be5db93ddb3efa7de6270880ad1b7dd5718` |
| Research-train content fingerprint | `sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033` |
| Existing M3D branch / PR / data | none |

All 8 immutable M3C artifacts hashed identically to the M3C acceptance baseline;
95 tracked upstream files under `research/m2b|m3a|m3b|m3c` were hashed and
recorded as the byte-identity baseline for the end-of-milestone comparison.

The M3C candidate is fixed and final:

- id `dual_horizon_trend_63_252_vol_target_30d_50pct`
- fingerprint `d45d3bdf7a3dca7003e8382995e5a350d0c9e61edf47e87e294d151070f4cae6`
- outcome `rejected_for_development_gate_promotion`

That rejection is permanent. The candidate must not advance to the development
gate and must not be evaluated again.

---

## 2. Data-only purpose

M3D exists to make the research program's history **machine-verifiable** and to
open a **strictly future-only** ETH-USD daily data facility, without spending any
scientific evidence budget:

1. Record the research-program history (M2B, M3A, M3B, M3C) as bound, hashed
   snapshots — without rewriting any prior artifact.
2. Catalog every benchmark, strategy specification, candidate, hypothesis,
   parameter set, experiment, decision, and data partition already exposed to the
   researchers, so hidden multiplicity and "forgotten" failed ideas cannot hide.
3. Classify the repeatedly-inspected research-train partition as **exhausted for
   new candidate research**, and enforce that classification with a guard API.
4. Establish a prospective cohort of newly-completed future ETH-USD daily candles
   that has **zero overlap** with the frozen M2B dataset.
5. Acquire and freeze only those future candles, with append-only, hash-chained,
   transactional provenance and independent reacquisition.
6. Hold the cohort **ineligible** for any performance evaluation until it reaches
   a hard maturity floor (≥ 365 completed daily observations) — and prove that
   even then, maturity is *data availability only*, never evaluation authorization.
7. Prove the facility contains **no** strategy, signal, backtest, position, fill,
   return, metric, ranking, promotion, or decision code.

---

## 3. Hard exclusions

Throughout M3D (mirrors §1 of the assignment):

- No re-evaluation of the rejected M3C candidate.
- No new strategy candidate; no new registered/executed financial experiment.
- No M3A run-004, M3B run-002, or M3C run-002.
- No parameter change; no optimize / grid-search / rank / select / compare.
- No strategy signal, backtest, position, fill, turnover, fee, return, P&L,
  equity, drawdown, CAGR, Sharpe, Sortino, PSR, bootstrap interval, or
  performance summary computed on prospective data.
- No inspection of the development gate or the final holdout.
- No append to either sealed access ledger.
- No modification of any tracked file under `research/m2b|m3a|m3b|m3c/` — all
  existing files remain byte-identical; no prior registry / manifest / report /
  result / decision / erratum / archive / evidence / raw / protocol is touched.
- No exchange auth, API keys, wallet, signing, order routing, live/paper trading,
  leverage, margin, borrowing, shorting, derivatives, ML, or optimization.
- No tag; no merge/undraft of any PR; no history rewrite; no force-push; no branch
  deletion; no GitHub Release.

**Import boundary.** M3D package code must contain no import path to a strategy,
backtest engine, fractional engine, accounting engine, result metric, promotion
decision, or experiment executor. Concretely, M3D must not import
`eth_research.strategies`, `eth_research.backtest`, `eth_research.metrics`,
`eth_research.fractional.engine`, `eth_research.fractional.accounting`, the M3A
evaluation/execution modules, the M3B experiment/evaluation modules, or the M3C
experiment/pipeline/statistics/decision modules. An AST-enforced architectural
test fails on any prohibited import. Shared strict-JSON, hashing,
canonicalization, timestamp, and data-quality utilities *may* be reused.

---

## 4. Package boundary and reused utilities

- Version bumps consistently to **0.7.0**: `pyproject.toml`,
  `src/eth_research/__init__.py`, `uv.lock`, and the version drift test
  (`tests/test_version.py`). The **frozen** milestone version constants
  (e.g. `eth_research.m3c.M3C_PACKAGE_VERSION = "0.6.0"`) are **not** changed;
  they are part of frozen replay identity, and all four upstream replays must
  keep reproducing after the bump.
- New isolated package `src/eth_research/m3d/` with modules:
  `validation.py`, `program_history.py`, `candidate_catalog.py`,
  `multiplicity.py`, `data_use.py`, `exhaustion.py`, `protocol.py`,
  `acquisition_plan.py`, `receipt.py`, `raw_bundle.py`, `segment.py`,
  `chain.py`, `cohort.py`, `publication.py`, `replay.py`, `status.py`,
  `hygiene.py` (plus `verify.py` for the graph verifier and `acquire_runner.py`
  for the strict offline acquisition parser).
- Reused shared low-level utilities (data-quality / provenance layer, **not**
  strategy/engine code): `eth_research._json` (`strict_json_loads`,
  `StrictJSONError`, `require_canonical_file_bytes`); `eth_research._atomic`
  (`write_atomic`, `publish_atomically`); `eth_research.data.validation`
  (UTC/day-aligned timestamp validators, `require_str/int/float`);
  `eth_research.data.provenance.sha256_bytes`; and the already-verified M2B
  Coinbase adapter contract in `eth_research.data.coinbase` (endpoint constant,
  row-format parsing, canonical UTC request formatting) for strict fail-loud
  parsing only. M3D defines its own `canonical_json_bytes` so the package stays
  self-contained and importable without any m3c coupling.

---

## 5. Research-history catalog (the governance core)

Four bound, verifiable governance artifacts, each with a strict model whose
construction and parsing share one invariant surface, each derived from committed
upstream artifacts (never a hand-written list that can drift):

1. **`research/m3d/research_program_snapshot.json`** — `ResearchProgramSnapshot`.
   Binds repo identity, upstream `main`/M3C base SHA, package version, the M2B
   frozen dossier hash, M2B dataset fingerprint/boundaries, M3A/M3B/M3C protocol
   / registry / results / report / trace / archive / decision hashes, both
   sealed-ledger facts (path, bytes, events, empty SHA), release-tag debt, and
   operational (hash-bound, not cryptographic) attestation status. Encodes the
   exact current conclusions (M2B real data frozen, gates untouched, M3C one
   candidate rejected, nothing promotable). `build_` / `verify_` provided.

2. **`research/m3d/research_specification_catalog.json`** —
   `ResearchSpecificationCatalog`. Every strategy specification exposed in
   M2B–M3C: cash; buy-and-hold; SMA(20,50); Donchian(55,20);
   vol-targeted buy-and-hold 30d/50%; vol-targeted Donchian(55,20,30d,50%);
   dual-horizon trend 63/252 vol-target 30d/50%; every cost scenario; every
   risk-overlay configuration; every drawdown-breaker state declared or executed.
   Each entry records role (`benchmark` | `exploratory_fixed_rule` |
   `measurement_instrument` | `candidate`), first-seen milestone/commit,
   immutable parameter mapping, specification fingerprint, datasets/partitions
   exposed, completed-experiment count, observed status, promotion eligibility,
   rejection reason, whether a parameter was selected after seeing results, and
   whether it may legally be evaluated again. The M3C candidate is
   `role=candidate, status=rejected, promotion_eligible=false,
   may_evaluate_again=false`. Cash and buy-and-hold are never labeled alpha
   candidates. Anti-orphan: every strategy identifier present in accepted
   protocols/results appears **exactly once**; reverse invariant: no catalog
   strategy may falsely claim execution absent from bound artifacts.

3. **`research/m3d/research_multiplicity.jsonl`** — append-only, hash-chained,
   genesis-sentinel ledger of every distinct research degree of freedom already
   exercised (strategy spec, candidate spec, parameter tuple, cost scenario, risk
   overlay, data partition, endpoint/statistic, bootstrap method, decision
   criterion set, experiment id, first-seen commit, milestone, role, status).
   Descriptive honesty — **not** retroactive multiple-testing correction. Strict
   decoder, exact schema, no duplicate identities, canonical order, previous-line
   hash chain, append-only verification, no repair/truncation tool, anti-orphan
   derivation, no "forgetting" of failed candidates. `verify_research_multiplicity`
   fails if any historical strategy/parameter/endpoint/experiment is missing.

4. **`research/m3d/research_data_use.jsonl`** — every legitimate historical data
   use (dataset fingerprint, partition, first/last timestamp, row count,
   milestone, experiment, use type ∈ {`integrity_only`, `schema_quality`,
   `research_development`, `replay_only`, `sealed_untouched`}, whether signals /
   P&L / metrics were computed, ledger/event evidence, source-artifact hashes).
   States truthfully that M2B train/validation and M3A/M3B/M3C research-train uses
   occurred; that the development gate and final holdout had **zero** strategy
   access; that the prospective M3D cohort is data-quality/provenance only. Any
   false "used a sealed partition" or "a used partition was unused" fails
   `verify_research_data_use`.

---

## 6. Adaptive-overfitting firewall (research-train exhaustion)

`research/m3d/research_train_exhaustion.json` + `ResearchPartitionPolicy` /
`ResearchTrainExhaustionDecision` classify the existing research-train partition
permanently as `exhausted_for_new_candidate_research`.

- **Allowed** future ops: byte-for-byte replay of accepted artifacts; schema /
  provenance verification; regression tests with pre-existing expected outputs;
  nonfinancial infrastructure tests; independent audit of published claims.
- **Forbidden** future ops: new candidate generation; new parameter selection;
  new ranking; new performance comparison; new bootstrap/statistical inference;
  selecting another candidate for the development gate; changing a strategy from
  observed research-train output; creating M3A run-004 / M3B run-002 /
  M3C run-002; relabeling an existing specification to evade the policy.
- Bound to the exact research-train content fingerprint and boundaries, the
  M3A/M3B/M3C artifact hashes, the M3C rejection, and the multiplicity- and
  data-use-ledger hashes.
- Guard API `require_operation_allowed(partition_identity, operation_kind)` is
  called by **every** new M3D entry point before touching data. Adversarial tests
  cover renamed candidates, copied protocols, alternate paths, changed
  versions/commits, new experiment ids, parameter aliases, and equivalent
  strategies under different names — all forbidden.

---

## 7. Prospective cohort

Pinned immutable protocol `research/m3d/prospective_protocol.json`
(`ProspectiveCohortProtocol`):

- base ETH / quote USD / symbol `ETH-USD` / venue `coinbase-exchange` / spot;
- interval 1 day; timestamp = candle open, UTC;
- source endpoint `https://api.exchange.coinbase.com/products/ETH-USD/candles`;
- **prospective start `2026-07-12T00:00:00Z`** — strictly after the final M2B
  candle open `2026-07-11T00:00:00Z`; zero overlap;
- completed UTC days only; no forming candle; no backfill before start; no gap
  fill; no interpolation; no sort/dedup/substitution repair;
- no strategy/candidate identifiers, no performance endpoints, no promotion rule,
  no optimization, no evaluation authorization.

**Maturity policy:** minimum 365 consecutive completed daily candles; fixed start;
nominal maturity last open `2027-07-11T00:00:00Z`, exclusive end
`2027-07-12T00:00:00Z`. Maturity means data availability only and never
authorizes strategy evaluation. Any future evaluation requires a separate
human-authorized milestone, a new protocol, a candidate declared *before* access,
and a new single-use evaluation ledger. The protocol is immutable once committed;
any update is a new schema/version that must not reinterpret existing rows.

**Prospective evaluation ledger `research/m3d/prospective_evaluations.jsonl`** is
created and tracked at **exactly zero bytes**, expected sha256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. No M3D code
in this milestone may append it — only read-only emptiness verification is
implemented. Any event is a HARD STOP.

---

## 8. Acquisition source, identity, interval, and fingerprints

Acquisition (§11–18) mirrors the reviewed, already-executed M2B facility, scoped
to the future window.

- **Source / identity:** public Coinbase Exchange candles endpoint (above); no
  auth, no secrets, no cookies, no redirect to another host.
- **Interval / timestamp convention:** 1-day buckets, candle-open UTC; Coinbase
  returns `[time, low, high, open, close, volume]` newest-first; the transformation
  maps to `timestamp, open, high, low, close, volume`, reversing only a strictly
  descending response and rejecting any other ordering.
- **Runtime window:** `overall_start = 2026-07-12T00:00:00Z`;
  `overall_end = first UTC midnight after the most recent fully completed day`,
  computed at execution time (expected `2026-07-15T00:00:00Z` at the current
  date — a 3-row genesis cohort covering opens 07-12/07-13/07-14 — but **not**
  hardcoded). Half-open windows; ≤ 299 daily buckets/request; exact contiguous
  tiling; ISO-8601 UTC request strings; reproducible plan hash; explicit user
  agent; no secrets; no overwrite by default.
- **Fingerprints:** raw-byte SHA-256 for exact retained response bytes, plus a
  domain-separated canonical-content fingerprint over ordered request ordinal,
  window bounds, raw filename, byte length, raw SHA-256, parsed row count,
  first/last open, and canonical per-row OHLCV — proving canonical output
  re-derives byte-for-byte from the retained raw bundle.

---

## 9. Incremental segment rules

Append-only `ProspectiveSegment` / `ProspectiveSegmentManifest` /
`ProspectiveSegmentChain` materialized at
`research/m3d/prospective_segments.jsonl`, each segment binding schema version,
segment id, previous segment-line hash, source-plan hash, attempt/receipt hash,
raw-bundle fingerprint, canonical-content fingerprint, first/last open, row count,
interval, created-at UTC, package version, source commit, and publication-bundle
hash. Genesis has no prior segment, the fixed cohort start, contiguous candles,
positive row count. Future segments start exactly one interval after the prior
last open, with no overlap/gap/duplicate/reorder/boundary-rewrite and immutable
prior segments; the chain verifies from genesis. Future-append fixtures are
implemented, but **no** second chronological extension is performed this
milestone.

---

## 10. Transactional publication

`research/m3d/prospective_manifest.json`, `prospective_quality.json`,
`prospective_segments.jsonl`, `reacquisition_audit.json`, and
`publication_manifest.json` are published transactionally via the shared atomic
primitive: precompute every blob, validate every model, hold a local publication
lock, write temp files in the destination, flush+fsync, atomically replace,
fsync directory, write the completeness marker last, read back + reparse + rehash,
verify the full graph, and roll back in reverse on any failure (fresh failure
leaves nothing; overwrite failure restores prior bytes exactly; no temp/backup/
lock debris). Failure is injected at every write/flush/fsync/replace/readback/
parse/verify position in both fresh and overwrite states. The manifest never
exists without a complete valid bundle.

---

## 11. Maturity, evaluation prohibition, and the cohort manifest

`ProspectiveCohortManifest` at `research/m3d/prospective_manifest.json` binds the
full identity, boundaries, row counts, maturity floor (365), nominal maturity
bounds, maturity state, remaining rows, every provenance hash (plan, receipts,
raw bundles, canonical, quality, segment chain, protocol, program snapshot,
multiplicity, data-use, exhaustion), the three evaluation/sealed ledger facts, and
the explicit flags `strategy_evaluation_performed=false`,
`candidate_declared=false`, `performance_metrics_computed=false`,
`promotion_decision_exists=false`. Terminal expected state: `maturity_state:
immature`, `evaluation_authorized: false`; no override flag can make it mature or
authorized.

Firewall (`ProspectiveMaturityState`, `evaluate_maturity`,
`require_data_only_operation`, `require_no_evaluation_capability`): maturity needs
≥ 365 rows, exact fixed start, continuous daily cadence, no unresolved errors,
primary/audit canonical match, and a complete provenance chain — **and even then,
maturity ≠ evaluation authorization.** M3D contains **no** evaluation function.
Standing tests prove immaturity, that falsified `as_of`/future-dated metadata
cannot create rows, that changing the minimum or renaming fields cannot bypass,
that adding a strategy id or performance endpoint is rejected, that engine imports
are caught by AST, that monkeypatching a loader cannot hand prospective rows to an
existing engine, that no public API returns a strategy-ready frame or exposes
OHLCV outside the internal verified replay path, and that the evaluation ledger
stays byte-empty. Existing strategy/engine entry points are instrumented and M3D
commands are asserted to call none.

---

## 12. Replay and CI

- `verify_m3d_program(repo_root)` — one graph-style verifier that **always** runs
  the complete 25-step chain (upstream anchors; three ledgers empty; M3C still
  rejected; snapshot; catalog; multiplicity; data-use; exhaustion; protocol; plan;
  primary receipt/raw; audit receipt/raw; reconstruct primary canonical;
  reconstruct audit canonical; compare; segment chain; quality; cohort manifest;
  publication manifest; no prohibited imports; no evaluation artifacts; immature;
  no smuggled strategy/candidate/performance fields; no write-capable acquisition
  workflow at final HEAD). No optional parameter may skip a check.
- `python -m eth_research.m3d.status --repo-root .` — data-only safe facts; never
  prints OHLCV, returns, signals, weights, positions, fills, P&L, equity, metrics,
  rankings, or recommendations; snapshot-tested for forbidden keys.
- `python -m eth_research.m3d.replay --repo-root . --check|--deep` — rebuilds
  everything from committed raw bytes alone, byte-exact canonical content across
  CPython 3.12.3 / 3.12 / 3.13, no tolerance (no strategy/statistics exist), no
  network, no engine call, no tracked-file mutation, all three ledgers byte-empty
  before/after; supports pristine / protocol-only / primary / primary+audit /
  published / contaminated fixture states (contaminated fails loudly).
- `.github/workflows/m3d-replay.yml` — `authoritative-replay` (3.12.3, frozen,
  deep) + `compat-replay` (3.12, 3.13), each pinned by SHA, hash-pinned uv,
  `uv lock --check`, locked sync, three ledgers empty before/after, offline
  replay, full graph verify, no strategy/engine import, no network, tracked tree
  unchanged. Normal CI is extended with M3D strict-parsing, architecture/import
  guard, firewall, maturity, and honest-JSON-state assertions. At final HEAD **no**
  workflow retains `contents: write`, Coinbase access, an acquisition trigger, a
  secret reference, a force push, an unpinned action, or a piped installer.

---

## 13. Threat model (summary; full model in `docs/M3D_THREAT_MODEL.md`)

Adversary goals defended against: (a) smuggling a strategy signal / backtest /
metric / promotion into a "data-only" facility; (b) laundering the exhausted
research train into new candidate research via renames, aliases, copied protocols,
or new experiment ids; (c) forging or "forgetting" research history to hide
multiplicity; (d) falsely claiming (or hiding) sealed-partition access; (e)
corrupting acquired data (gap fill, substitution, reorder, forming candle,
overlap with M2B, primary/audit divergence) without detection; (f) a supply-chain
or path attack via the acquisition workflow; (g) faking maturity or authorization
via metadata/`as_of` manipulation; (h) leaving a dormant write-capable workflow.
Every refusal must occur **before** any prohibited calculation.

## 14. Test plan (summary; full matrix implemented under §27)

Strict JSON (dup keys at every depth, NaN/±Inf, exponent overflow, bool-as-int,
numeric strings, null, unknown/missing keys, wrong containers); acquisition
(HTTP-error-with-200, wrong row width, non-numeric/non-finite candle fields,
unaligned epoch, duplicate/shuffled/pre-start/end-boundary/forming rows, missing
day, oversized body, wrong content type, redirect, source mutation, mismatched
sidecar); chain (overlap/gap/duplicate/reorder/changed-genesis/broken-hash/extra/
removed/symlink/traversal); governance (omitted candidate/experiment, mislabeled
benchmark, rejected-marked-eligible, changed verdict, false gate claim, hidden
alias, alternate id, copied protocol, changed version, relabeled dataset, same
strategy renamed, research-train reuse attempt); publication (failure at every
position, fresh/overwrite rollback, readback corruption, early manifest, honest
rollback-failure); firewall (strategy/binary-engine/fractional-engine/metric/
renderer spies, gate/holdout poison, evaluation-ledger mutation). Targeted tests
during development; full suite reserved for major checkpoints.

## 15. Red-team plan (summary; §28)

After implementation and before final docs, three independent read-only auditors —
A provenance/data, B governance/firewall, C security/reproducibility — each
assume tests are incomplete, work read-only, cite files/functions, and classify
findings Class A (data/provenance) / B (governance/firewall) / C (testing/docs/
operability) / D (sealed access or strategy evaluation). Every accepted finding is
reproduced by me: failing test first → root cause → minimal fix → regression
coverage → replay-neutral proof → bug-log entry → separate commit. **Any Class D
finding is a HARD STOP.**

---

## 16. Ordered commit plan

Small, append-only commits (fast-forward pushes only; no amend/squash/rebase/
reset/force-push):

1. M3D plan (this document, alone).
2. Version 0.7.0 + isolated `m3d` package boundary + AST import guard.
3. Research-program snapshot.
4. Specification catalog.
5. Multiplicity ledger.
6. Data-use ledger.
7. Research-train exhaustion policy.
8. Prospective protocol + empty evaluation ledger.
9. Acquisition models + strict runner.
10. Workflow-security / failure-injection tests.
11. Primary acquisition plan + one-shot trigger workflow.
12. Primary bot acquisition commit (`coinbase-eth-usd-prospective-genesis-001`).
13. Independent audit acquisition plan/trigger.
14. Audit bot acquisition commit (`coinbase-eth-usd-prospective-audit-002`).
15. Raw-bundle + transformation evidence.
16. Segment chain.
17. Transactional publication.
18. Quality + cohort manifest.
19. Full graph verifier.
20. Status / replay CLIs.
21. M3D Replay CI + extended normal CI.
22. Workflow retirement (delete write-capable acquisition workflow).
23. Adversarial / firewall / hygiene suite.
24. Red-team fixes (one per accepted finding).
25. Findings + documentation.
26. Terminal audit.
27. Any final CI-only fix-forward commit.

---

## 17. Hard stops

Stop immediately (no repair, no substitution) if: any sealed ledger becomes
nonempty; any prior immutable artifact drifts; M3C is re-executed or its verdict
changes; the prospective evaluation ledger gains any event; Coinbase returns no
completed row, a gap, malformed data, or changed semantics; primary and audit
canonical content differ; a Class D red-team finding is confirmed; or the remote
head moves unexpectedly during acquisition.

## 18. Terminal deliverables

- Branch `claude/m3d-prospective-evidence-governance` from `c508724`; a **draft
  stacked** PR (base `claude/m3c-adaptive-research-governance`, head the M3D
  branch) opened only after final-head CI is fully green.
- Docs: `M3D_THREAT_MODEL.md`, `M3D_PROSPECTIVE_PROTOCOL.md`, `M3D_ACQUISITION.md`,
  `M3D_MULTIPLICITY_NOTE.md`, `M3D_RESEARCH_TRAIN_EXHAUSTION.md`, `M3D_BUG_LOG.md`,
  `M3D_FINDINGS.md`, `M3D_TERMINAL_AUDIT.md`, `research/m3d/README.md`; updated
  `README.md` and `docs/PLAN.md`.
- A read-only terminal audit with the required 41-item content and the verdict:

  > MILESTONE 3D COMPLETE — PROSPECTIVE COHORT IMMATURE, NO STRATEGY EVALUATED

The correct endpoint is deliberately uneventful: M3C candidate remains rejected;
the old research train is closed to new candidate research; the development gate
and final holdout remain untouched; a small, strictly future-only, provenance-
complete but **immature** data cohort exists; no strategy has been tested on it;
no trading claim exists.
