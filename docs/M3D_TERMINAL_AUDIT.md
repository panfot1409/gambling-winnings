# Milestone 3D — Terminal Acceptance Audit

A read-only acceptance audit of the completed Milestone 3D prospective-evidence
governance facility, stacked on the accepted M3C head `c508724`. Every item below
was verified against the committed tree; the whole chain is reproduced by
`python -m eth_research.m3d.verify_m3d_program` (25 checks) and by
`python -m eth_research.m3d.replay --repo-root . --deep`.

## Scope and posture

Milestone 3D is **data-only and governance-only**. It created, evaluated, ranked,
tuned, promoted, and reported performance for **no** strategy. Its deliverable is
epistemic: a machine-verifiable research-program history, an adaptive-overfitting
firewall closing the exhausted training data, and a strictly non-overlapping,
future-only prospective ETH-USD daily cohort that is **immature** and not
evaluation-authorized.

## Audited items

### Baseline & isolation
1. Stacked on the accepted M3C head `c508724`; 32 append-only M3D commits;
   fast-forward pushes only; no amend/squash/rebase/force-push/tag.
2. Package version is `0.7.0`; the bump is replay-neutral (each frozen milestone
   pins its own version constants).
3. The M3D code lives in an isolated `src/eth_research/m3d/` package.
4. An AST import guard (allow-list) permits only strategy-free shared utilities;
   no engine/strategy/backtest/metrics/evaluation import is present.
5. Every prior immutable artifact (M2B/M3A/M3B/M3C) is byte-identical; the
   upstream anchors rebuild and hash unchanged.

### Sealed state (untouched)
6. The development-gate access ledger is **byte-empty** (0 bytes).
7. The final-holdout access ledger is **byte-empty** (0 bytes).
8. The dev gate and final holdout were never inspected or evaluated.
9. The M3C candidate decision still carries
   `rejected_for_development_gate_promotion`.
10. No M3A run-004 / M3B run-002 / M3C run-002 was executed.

### Research-history governance
11. `research_program_snapshot.json` rebuilds and verifies.
12. `research_specification_catalog.json` catalogs every benchmark/strategy
    specification, cost scenario, and risk overlay; anti-orphan both directions.
13. `research_multiplicity.jsonl` (hash-chained) records every research degree of
    freedom — descriptive honesty about the search surface, not a p-value
    correction.
14. `research_data_use.jsonl` records historical data use with a symmetric
    sealed-partition firewall; it stays byte-frozen (the prospective cohort's
    record lives in the cohort manifest, avoiding a provenance cascade).
15. `research_train_exhaustion.json` declares the training partition exhausted for
    new candidate research, with a fail-closed, fingerprint-resolved guard.

### Prospective cohort acquisition
16. The prospective evaluation ledger `prospective_evaluations.jsonl` was created
    **byte-empty** and never appended.
17. Cohort start is fixed at `2026-07-12T00:00:00Z`, strictly after the final M2B
    open `2026-07-11`.
18. Two independent acquisitions ran via GitHub Actions: genesis
    (`coinbase-eth-usd-prospective-genesis-001`, run `29424691776`, source commit
    `02a92e8`) and audit (`coinbase-eth-usd-prospective-audit-002`, run
    `29424930094`, source commit `c4aa95e`).
19. The network boundary is a hardened `curl` step; the Python runner opened no
    socket (repo hygiene forbids network/wallet imports across src/tests/examples).
20. Acquisition fetched only newly-completed public candles: request window
    `[2026-07-12, 2026-07-14]` inclusive (the forming `2026-07-15` candle excluded
    by the inclusive-end / half-open convention).
21. Each retained raw body is SHA-256-bound by its receipt; the receipts record
    body hashes and lengths, never candle values.
22. The genesis and audit raw bodies are byte-identical; independence is enforced
    by distinct source commits and distinct workflow-run ids.

### Transformation, segment, quality
23. The raw→canonical transformation delegates to the reviewed M2B adapter and
    re-derives byte-for-byte: 3 completed daily candles, opens `2026-07-12/13/14`.
24. The delivered cohort is bound to the pre-registered plan window (row count ==
    planned buckets; last open reaches `window_end - 1 day`).
25. The cohort canonical fingerprint is
    `bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507`.
26. `prospective_segments.jsonl` is an append-only hash chain (genesis sentinel +
    one segment at the fixed cohort start); the incremental-append rules
    (contiguity, no overlap/gap/duplicate/reorder) are implemented and tested.
27. `reacquisition_audit.json` proves the two attempts reproduce identical
    canonical content (zero differing candles/fields) under distinct provenance.
28. `prospective_quality.json` reports **zero** structural errors; overlap with
    the frozen M2B dataset is a HARD STOP; warnings never rank/label/select.

### Cohort manifest & publication
29. `prospective_manifest.json` binds identity, boundaries, row count, the 365
    maturity floor, nominal maturity bounds, and every governance + acquisition
    provenance hash (including the specification-catalog hash).
30. Terminal manifest state: `maturity_state: immature`,
    `evaluation_authorized: false`, and `strategy_evaluation_performed /
    candidate_declared / performance_metrics_computed / promotion_decision_exists`
    all **false**.
31. `publication_manifest.json` is the completeness marker binding every non-marker
    artifact by hash; the transactional publisher is all-or-nothing with
    readback+reparse+rehash and rollback (failure-injection tested).
32. Cohort maturity: **3** of **365** required observations; **362** remain;
    nominal maturity no earlier than the `2027-07-11` open.

### Firewall & verifier
33. `evaluate_maturity` re-derives maturity from committed evidence and asserts
    the floor (hard literal 365) and that evaluation stays unauthorized even when
    mature.
34. `require_data_only_operation` fails closed on evaluate/backtest/rank/promote/
    decide; `require_no_evaluation_capability` rejects any evaluation-output
    artifact and confirms the evaluation ledger byte-empty.
35. `verify_m3d_program` runs a complete **25-check**, un-skippable chain (no
    optional parameter); the import scan is an allow-list, the forbidden-field
    scan matches keys and values across all five artifacts, and the workflow scan
    covers `*.yml` + `*.yaml`.
36. Three independent read-only red teams (provenance, governance/firewall,
    security/repro) returned **no Class D** finding; every Class C defense-in-depth
    gap was fixed with a regression test (`docs/M3D_FINDINGS.md`).
37. A standing adversarial suite proves the fortress fails closed on ledger
    contamination, M3C-verdict flip, smuggled evaluation artifact/field, forced
    maturity, tampered raw byte, mutated segment chain, and injected prohibited
    import.

### CI, replay, retirement
38. The status CLI emits only safe governance facts and leaks no OHLCV, return,
    signal, weight, position, P&L, equity, metric, or ranking.
39. `replay --deep` rebuilds every artifact byte-exact, opens no socket, calls no
    engine, mutates no tracked file, and proves all three ledgers byte-empty before
    and after — across CPython 3.12.3 / 3.12 / 3.13.
40. `.github/workflows/m3d-replay.yml` (authoritative + compat) and the extended
    normal CI honest-state gate are green; every action is SHA-pinned and uv is
    hash-pinned.
41. The one-shot acquisition workflow and its push sentinel are **deleted** at the
    final HEAD; no workflow grants `contents: write` or contacts Coinbase, and any
    future acquisition must arrive as a new, separately reviewed workflow commit.

## Residual limitation (documented, by design)

The prospective cohort is self-anchoring: future-only candle bytes are bound to
committed receipts with no external value oracle. An offline verifier proves
internal consistency and reproducibility, not authenticity against an outside
source; the two genuinely independent acquisitions (distinct commits/run-ids) are
the strongest offline authenticity control, and their run-ids are the
external-audit hook.

## Verdict

**MILESTONE 3D COMPLETE — PROSPECTIVE COHORT IMMATURE, NO STRATEGY EVALUATED.**
