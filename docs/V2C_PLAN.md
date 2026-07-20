# V2C Plan — Prospective-Evidence Governance, Candidate-Free Operational Qualification, Process-Isolated Buyer Evaluation

**Milestone V2C** is a candidate-free, data-only foundation built on the merged V2A and V2B
**null** results. V2C **does not evaluate any trading strategy**. It prepares — but does not
activate — a future prospective-data proposal system; qualifies the offline operations platform
under deterministic synthetic stress; proves a process-isolated buyer-evaluation boundary;
preserves the legacy-research moratorium; and states honestly that **V2 remains not sell-ready**.

Active development version: **`2.0.0.dev2`** (V2A froze at `2.0.0.dev0`; V2B at `2.0.0.dev1`).
Branch: `claude/v2c-prospective-operations-qualification`, created from the verified merged `main`
at **M2**. This plan is committed **before** substantive implementation and freezes the scope below.

## Stacked-merge handoff (PART I, completed)

The independently accepted V2A→V2B stack was merged into `main` using true two-parent merge commits.

| Anchor | SHA | Notes |
|---|---|---|
| M0 (pre-merge `main`) | `30e119933feb3d30cf3a890b177ea24b14ffc0da` | tree `a778bc7e` |
| A (V2A head, PR #16) | `d437dafd67047470eae2c88fb14f0d8db6bf7091` | tree `ccbd6007`; branch retained |
| B (V2B head, PR #17) | `b3654c64091034feffce0d721009d9a723f6ff27` | tree `d11c19e8`; branch retained |
| M1 (merge #16) | `812ba815f96ee65678e821fa85cb479ffefa2c0f` | parents [M0, A]; tree(M1)==tree(A) |
| M2 (merge #17) | `6e0d60ef6daf638fe1c9df63ced650015545b819` | parents [M1, B]; tree(M2)==tree(B) |

- Retarget of PR #17 onto `main@M1` preserved patch identity exactly: `patch-id(A..B)` ==
  `patch-id(M1..B)` == `3fa3360bef0563506f6a66422bd10d21525328de` (145 files, +22901/−41).
- `rev-list M0..M2` = 61 = 59 stack commits + 2 merge commits; 0 missing, 0 duplicated.
- Governed-state digest unchanged: `b2077eaf…` (== frozen merged-main M3 baseline).
- Both feature branches retained; **no tag** created (a development version is not a release).
- M1 CI and M2 CI both terminal-green across every workflow (CI 3.12/3.13/authoritative + all
  replays incl. V2A, V2B, V2AB Stack Acceptance).

`main` at M2 is tree-identical to accepted B and must remain so; V2C is built only on its own branch.

## Frozen scope

### 1. No strategy — candidate-free
V2C cannot evaluate a strategy. A first-gate execution firewall (§14) rejects any candidate id,
candidate fingerprint, strategy/signal callable, candidate module, research protocol, financial
endpoint, nomination rule, return/equity metric, benchmark, optimization request, or
market-performance report. The **only** allowed operational target is `cash_control` — not a
strategy — which always requests zero risky exposure, zero notional, zero fills, zero turnover.
Tests monkeypatch every candidate/engine entry point and prove none is reached.

### 2. Synthetic-only operational qualification
The operational platform is qualified under **deterministic virtual time** (no wall-clock waiting)
against a synthetic ETH/BTC event stream (§20): ≥3650 daily event slots with normal/gap/stale/
duplicate/conflicting-duplicate/out-of-order/high-volatility/zero-volume periods, delayed receive
times, checkpoint boundaries, injected restarts, disk-write failures, corrupted checkpoint/journal
attempts, alert bursts, and reset attempts. The cash-control target stays zero throughout; the run
computes **no** market performance. This is **not** a forward record.

### 3. Prospective proposal lifecycle (prepared, not activated)
A strict prospective cohort schema + state machine (§15), a source-independent update-proposal
format (§16), and an offline proposal generator (§17) are built. **No real new candles are fetched
or ingested in V2C.** All strategy/evaluation flags stay false. A future activation workflow exists
only as an **inactive template** outside `.github/workflows` (§18); the final V2C HEAD contains no
new standing write-capable workflow. Maturity (§19) never depends on strategy outcomes;
`evaluation_authorization` stays false even if data maturity later becomes true (a separate future
human authorization is still required).

### 4. Process-isolated buyer evaluation
A process-isolated local buyer boundary (§24) uses fixed argv, `shell=False`, length-prefixed JSON,
bounded request/response sizes, no network/pickle/eval; the buyer process runs from a temp root with
no repository, package source, or private data. Honest limitation: the vendor still runs the private
implementation — this is **not** independent deployment and does not prove the core IP cannot be
reverse engineered.

### 5. No network activation; no standing write workflow
No network call, no live/paper trading, no broker/exchange integration, no credentials, no wallets,
no order routing, no leverage/borrow/margin/shorts/derivatives, no public deployment, no public
publication, no PyPI/TestPyPI, no GitHub Release, no LICENSE, no V2 tag.

### 6. Qualification criteria (offline SLOs, not production promises)
Event-acceptance correctness, duplicate suppression, conflicting-duplicate detection, journal
durability, checkpoint consistency, recovery idempotency, kill-switch trip latency (in event
steps), alert completeness, state-reconstruction success, bounded processing/memory on the
reference fixture, and **zero unintended intents / zero unintended fills** (§21). These are internal
offline objectives, not live-production SLAs.

### 7. Source-free buyer-process criteria
The buyer harness (§27) is deterministic, double-builds byte-identically, and contains only public
schemas/client/examples/checksums — no strategy source, wheel, bytecode, raw data, or private URLs.
It is not uploaded or published.

## Hard stops (any → terminal STOP)
A strategy function called by V2C; a candidate created or evaluated; V2A/V2B logic changed or
re-run; a sealed development-gate or final-holdout value read; an M3D prospective value evaluated;
M3E activated; real market data fetched; a standing write-capable acquisition workflow activated;
real signals generated from prospective data; a forward performance record created; prospective
price values reaching a signal/engine/metric/report; the legacy-research moratorium weakened;
`sell_ready` becoming true; a public-publication path appearing; `main` modified outside the
authorized merge sequence; a Class-A scientific or Class-D governance defect found.

## Sequence: OQ-E → OQ-R → OQ-P → OQ-Q
- **OQ-E** (§35) — source freeze on a green tree (plan, firewall, proposal system, inactive
  template, frozen synthetic fixture + fault schedule + SLOs, buyer boundary/harness, claims/
  readiness, auditors closed); push, all CI green; no qualification-source change after OQ-E.
- **OQ-R** (§36) — register the qualification protocol, synthetic fixture manifest, fault schedule,
  SLO contract, cash-control identity, source freeze, runtime, buyer-harness hash, readiness
  pre-state, and one `registered` event; no source change; push, CI green.
- **OQ-P** (§37) — execute the synthetic qualification exactly once via the public orchestrator
  (`registered → started → completed|failed`). Expected: risky intents = 0, fills = 0, turnover = 0,
  strategy calls = 0, performance metrics absent. No rerun after `started`.
- **OQ-Q** (§38) — independently reconstruct qualification from the fixture/fault-schedule/journal/
  checkpoints/alerts/recovery/SLO evidence; do not trust the committed pass field.

The dedicated non-financial qualification registry
(`v2c_offline_operational_qualification_run_001`) is separate from research-experiment registries
and sealed-access ledgers; any candidate/strategy reference invalidates the qualification.

## Auditors
- **Pre-qualification (§34, five):** (1) no-strategy firewall + moratorium; (2) prospective
  proposal governance + future workflow template; (3) operational safety/journal/kill-switch/
  recovery; (4) buyer process boundary/framing/redaction/source leakage; (5) packaging/SBOM/IP/
  commercial honesty. Reproduce every finding; fix genuine ones failing-test-first; no qualification
  until all Class A/D closed.
- **Post-qualification (§39, five):** independent operational oracle; crash/recovery + journal
  forgery; prospective-governance bypass; buyer boundary/source leakage; claims/readiness/commercial
  honesty. A result-invalidating operational defect → preserve qualification, append invalidation,
  no rerun, terminal verdict reflects failed qualification. Result-neutral fixes forward + regressions.

## Final PR topology
One **draft** PR, `base: main`, `head: claude/v2c-prospective-operations-qualification`, opened only
after the complete milestone is finished and terminal CI is green. Do **not** merge, undraft, or
retarget it. The V2C replay workflow (`.github/workflows/v2c-replay.yml`, §40) is read-only (no
write permissions, secrets, id-token, schedule, exchange host, artifact publication, tags, or
releases).

## Terminal verdicts (exactly one)
- Qualification passes: `V2C COMPLETE — PROSPECTIVE-EVIDENCE AND OFFLINE-OPERATIONS QUALIFICATION
  READY, NOT ACTIVE; NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`
- Qualification fails validly after `started`: `V2C COMPLETE WITH FAILED OPERATIONAL QUALIFICATION —
  FAILURE PRESERVED; NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`
- Hard stop: `V2C STOPPED — GOVERNANCE, SAFETY, OR MERGE-INTEGRITY HARD STOP`

## Absolute final stop
At terminal state: leave the V2C PR open and draft; do not merge/undraft/tag/publish/add a LICENSE/
activate the prospective workflow/fetch real data/evaluate a strategy/create a candidate/open a
research budget/access the development gate or final holdout/inspect prospective performance/
activate M3E/create a live adapter/route an order/delete branches/rewrite history/start V2D. The
repository remains private.
