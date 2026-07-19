# V2B Plan — cross-asset research reset on the accepted V2A null

Milestone **V2B** continues the V2 sell-ready roadmap on top of the **accepted V2A negative result**:

> V2A COMPLETE — NO CANDIDATE NOMINATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.

V2A's null is treated as **evidence, not a problem to disguise**. V2B does **not** retune V2A's rejected
candidates. Instead it (1) independently accepts V2A as an immutable base, (2) introduces a genuinely
**new information source** — historical **BTC-USD** daily data restricted to the already-authorized
research-train period — (3) formally accounts for **cumulative research exposure** (family-level
multiplicity), (4) pre-registers **at most two** genuinely new cross-asset candidate families, and
(5) runs **exactly one** new research-train experiment under materially stricter multiplicity control.

This is a research-and-evidence milestone. Its best possible outcome is at most **one** research-stage
nomination handed to an independent development-gate review — never a sell decision. V2 stays
`not_sell_ready` regardless of outcome.

## Active version

`2.0.0.dev1` (V2A froze at `2.0.0.dev0`; see `eth_research.v2.V2A_PACKAGE_VERSION`). Branch
`claude/v2b-cross-asset-research-reset`, stacked on the accepted V2A tip
`d437dafd67047470eae2c88fb14f0d8db6bf7091` (PR #16). The terminal V2B draft PR targets
`base: claude/v2a-commercial-evidence-shadow-platform`, `head: claude/v2b-cross-asset-research-reset`.
PR #16 is **not** retargeted or modified.

## Absolute scientific firewall

The only authorized performance-evaluation interval is **2016-05-23T00:00:00Z … 2022-06-21T00:00:00Z
inclusive** (the accepted ETH research-train partition, **2221** daily rows). BTC is acquired only for
the exact matching half-open window **[2016-05-23T00:00:00Z, 2022-06-22T00:00:00Z)** — no context row
before the start, no row at/after the end, no forming candle.

Sealed and unreadable by any strategy / engine / metric / diagnostic / report / statistic / decision:
the development gate, the final holdout, M2B's test partition, M3D's prospective cohort, all M3E
prospective machinery, every observation after 2022-06-21, and any forming candle. A single sealed row
reaching any candidate, benchmark, context frame, engine, cost model, bootstrap, Monte-Carlo routine,
renderer, or decision is a **Class-D hard stop**. Test spies assert, for both instruments and context:
`max(engine/context timestamp) < first sealed timestamp`.

## Out of scope (gated on separate human authorization)

Development-gate access; final-holdout access; M3D prospective evaluation; M3E activation; prospective
mutation; live / connected paper trading; exchange credentials or authenticated endpoints; broker
connectivity; order routing; wallets; signing; leverage; borrowing; margin; shorts; derivatives; public
deployment; public data/artifact publication; PyPI/TestPyPI; a GitHub Release; adding a LICENSE; merging
or undrafting PR #16 or the new V2B PR; tagging; modifying `main`; branch deletion; history rewriting;
rerunning V2A; changing any V2A artifact; reviving a rejected M3C/V2A candidate under a new name;
executing V2B more than once. The repository and every acquisition artifact stay **private**.

## Hard-stop taxonomy

- **Class A** — scientific / financial integrity (would corrupt the one-shot research result). HARD STOP.
- **Class D** — sealed-partition or governance breach. HARD STOP.
- **Class B / C** — correctness / defense-in-depth / honesty hardening that touches no sealed partition
  and changes no pre-registered scientific quantity. Fixed forward, append-only.

## The governed sequence (E → R → P)

1. **Part I — independent acceptance of V2A** (four read-only auditors → `docs/V2A_INDEPENDENT_ACCEPTANCE_AUDIT.md`).
   Verdict must be `V2A NEGATIVE RESULT ACCEPTED AS IMMUTABLE RESEARCH EVIDENCE`, else V2B stops before
   new research.
2. **Research-memory & multiplicity** — a cumulative, immutable research-family catalog + append-only
   hash-chained exposure ledger + semantic anti-relabel verifier; a pre-registered family-wise
   error / alpha-spending policy that accounts for *all* prior families (M3A/M3B/M3C/V2A) plus V2B.
3. **Hypothesis review** (primary sources, cited) → `docs/V2B_HYPOTHESIS_REVIEW.md`, then freeze the
   candidate family definitions and parameters **before** any real BTC byte enters the branch.
4. **Candidates** — ≤ 2 genuinely new cross-asset families (A: BTC-confirmed ETH trend exposure;
   B: ETH/BTC/cash long-only relative-strength rotation), developed and tested on **synthetic** panels
   with independent scalar-loop oracles; a candidate-distinctness matrix vs M3A/B/C/V2A and each other;
   a BTC information-dependence test (no ETH-only fallback; missing BTC → refusal).
5. **BTC acquisition** — strict immutable request plan; a temporary hardened one-shot workflow
   (`contents: write` only, no `id-token`/secrets, SHA-pinned, push-sentinel bootstrap, no overwrite,
   fast-forward-only bot commit); **two** independent acquisitions (genesis + audit) that must reproduce
   **identical canonical candles**; then retire the workflow and freeze the canonical BTC dataset.
6. **Joint partition + engine** — an immutable aligned ETH/BTC partition (built internally from
   manifests/locks, caller frames untrusted); reuse the accepted **M4B** portfolio engine unmodified
   for a long-only ETH/BTC/cash run (USD base, no FX/corp-action, daily calendar, gross ≤ 1, no short/
   leverage); pre-registered benchmarks (cash, ETH buy-and-hold, BTC buy-and-hold, static 50/50),
   per-instrument proxy costs (≥ 4 scenarios), capacity/latency, walk-forward folds + causal regimes,
   a small frozen sensitivity neighborhood, fold-stratified moving-block bootstrap + Monte-Carlo
   diagnostics + the cumulative multiplicity correction, and a stringent primary nomination rule
   (≤ 1 nomination; none if neither passes).
7. **Governance** — a fresh V2B one-shot budget + canonical append-only hash-chained registry
   (`registered → started → completed|failed`; a `started` consumes the budget permanently); a
   multi-asset (ETH/BTC/cash) offline vector shadow extension; a buyer-evidence update that preserves
   every prior negative limitation and keeps `sell_ready` false.
8. **E freeze → R register → P execute** — five-auditor pre-registration red team must close every
   Class A/D before **E** (source freeze, CI green); **R** commits governance/artifacts only (one
   `registered` event; tree E == tree R; CI green); **P** runs the fail-closed orchestrator exactly
   once, appends `started`, evaluates, applies the corrected decision, publishes a closed immutable
   archive, appends `completed`.
9. **Post-run** — five fresh auditors; fresh-clone reproduction on CPython 3.12.3 / 3.12 / 3.13; a
   read-only `v2b-replay.yml`; the full documentation set; one draft stacked PR (no merge/undraft/
   retarget); a ≥ 120-item terminal audit; exactly one terminal verdict; **absolute final stop**.

## Reuse (no accepted engine is modified)

- **M4B portfolio engine** — `eth_research.portfolio` (`run_portfolio_simulation`, `build_market_panel`,
  `PortfolioProtocol`, `solve_shared_cash`, accounting/attribution/costs/result).
- **Statistics** — `eth_research.m3c.statistics` (fold-stratified moving-block bootstrap, fixed seed /
  resamples / percentile), `eth_research.walkforward`, `eth_research.metrics`.
- **Risk overlays** — `eth_research.fractional.risk` (`ANNUAL_VOLATILITY_TARGET`, `VOLATILITY_LOOKBACK`).
- **Governance scaffold** — `eth_research.v2` (constitution, budget, append-only hash-chained registry,
  publication, orchestrator, pre-registration, replay verifier, decision).
- **Research-memory precedent** — `eth_research.m3d` (`multiplicity`, `data_use`, `candidate_catalog`,
  `program_history`, `chain`).
- **Acquisition precedent** — `eth_research.data` (M2B) and `eth_research.m3d` acquisition/receipt/
  raw-bundle/reacquisition-audit machinery.

New code lives under `eth_research.v2b` (+ `research/v2b/`, `tests/test_v2b_*.py`, `docs/V2B_*.md`, a
read-only `.github/workflows/v2b-replay.yml` added to the closed `KNOWN_WORKFLOW_FILES` allowlist).

## Terminal verdicts (exactly one)

- One candidate passes → `V2B COMPLETE — ONE GENUINELY NEW CROSS-ASSET RESEARCH CANDIDATE NOMINATED FOR
  INDEPENDENT DEVELOPMENT-GATE REVIEW; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`.
- None passes → `V2B COMPLETE — NO CROSS-ASSET CANDIDATE NOMINATED; CUMULATIVE NEGATIVE EVIDENCE
  PRESERVED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`.
- One-shot consumed without a valid result → `V2B TERMINATED — ONE-SHOT CONSUMED WITHOUT A VALID
  NOMINATION; ALL SEALED PARTITIONS UNTOUCHED`.
- Integrity/governance hard stop before execution → `V2B STOPPED — DATA, GOVERNANCE, OR
  SCIENTIFIC-INTEGRITY HARD STOP; ONE-SHOT NOT EXECUTED`.

No claim of edge, alpha, validation, deployment readiness, or sell-ready status is made anywhere.
