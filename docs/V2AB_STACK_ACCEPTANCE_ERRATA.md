# V2A–V2B Stack Acceptance — Append-Only Errata

This is an **append-only, post-run erratum register** produced by the independent V2A–V2B
stack-acceptance program. It exists so that the minor (Class C) observations surfaced by the
five independent acceptance auditors are recorded **without editing any immutable accepted
artifact in place**.

Governing rule (from `docs/V2AB_STACK_ACCEPTANCE_PLAN.md` §1): no accepted financial or
scientific artifact may be changed; any post-run correction must take the form of a new
verifier, a new generated summary, an append-only annotation, a **hash-bound erratum**, or an
invalidation record. Every entry below that annotates an immutable document binds that
document by its accepted SHA-256, so this register annotates *exact bytes* and cannot silently
drift.

None of the items below is a Class A (scientific/financial-integrity) or Class D
(sealed/governance) defect. Every immutable result, registry event, dataset fingerprint, and
sealed ledger is unchanged. These are display, documentation-freshness, and
verifier-comment observations only. The two immutable documents referenced here are **not**
edited; the one verifier-source item is corrected *forward* (a new descendant commit) because
verifier source is on the verifier side, not the frozen side.

## Accepted anchors

| Anchor | Value |
|---|---|
| Accepted `main` base | `30e119933feb3d30cf3a890b177ea24b14ffc0da` |
| Accepted V2A terminal HEAD | `d437dafd67047470eae2c88fb14f0d8db6bf7091` |
| Accepted V2B terminal HEAD | `5798610389af0905331fc5da20f54f4b8f7930fb` |
| `docs/V2A_FINDINGS.md` SHA-256 (accepted bytes) | `106500ad70adb97d93c9490ae875294533d6345f48de5c4befacad86b16c348c` |
| `docs/V2B_ACQUISITION.md` SHA-256 (accepted bytes) | `af107889ce719cc5cb18d35a205fcc4b091a032a18a8dedfc722dbbfe2e79de0` |

If either accepted SHA-256 above no longer matches the committed bytes, the annotated entry
must be re-derived before relying on it (the erratum is bound to those exact bytes).

---

## E-1 — V2A findings display rounding (Auditor 1, Class C, non-invalidating)

- **Where:** `docs/V2A_FINDINGS.md:40`, bound to accepted SHA-256
  `106500ad70adb97d93c9490ae875294533d6345f48de5c4befacad86b16c348c`.
- **Observation:** the `vol_scaled_hold_drawdown_guard` primary-CI lower bound is displayed as
  `−0.002253`. The committed authoritative value is `−0.002252266903046442`, which rounds to
  `−0.002252` at six decimal places; the displayed figure is off by one in the last shown
  digit.
- **Why it does not invalidate anything:** the authoritative bound lives in the accepted V2A
  results JSON (unchanged and independently reconstructed byte-for-byte by the V2A oracle). The
  bound is negative on either rounding, so the primary nomination gate is unaffected — the
  family is `research_stage_rejected` regardless. Non-pivotal cosmetic display only.
- **Disposition:** recorded here; **not** corrected in place (immutable accepted document).
  No result, fingerprint, or decision changes.

## E-2 — V2B acquisition doc has an un-filled run-evidence template (Auditor 3, Class C-1, non-blocking)

- **Where:** `docs/V2B_ACQUISITION.md:113-125`, bound to accepted SHA-256
  `af107889ce719cc5cb18d35a205fcc4b091a032a18a8dedfc722dbbfe2e79de0`.
- **Observation:** the "Run evidence" table still shows the pre-acquisition template with every
  cell `_(pending)_` (workflow run id, source commit, receipt SHA-256, parsed daily opens,
  first/last open, canonical fingerprint), even though the two BTC acquisitions completed.
- **Why it does not invalidate anything:** the authoritative run evidence is recorded and
  reproduced elsewhere — the two acquisition receipts, the dataset lock, the joint partition
  identity, and the independent BTC-acquisition audit, all of which the acceptance oracle
  re-derives from raw candle bytes and confirms green (`verify_btc_acquisition == []`,
  genesis/audit fingerprints identical and equal to the committed and accepted anchors). The
  doc table is a cosmetic un-filled template, not a source of truth.
- **Disposition:** recorded here; **not** corrected in place (immutable accepted document).

## E-3 — V2B acquisition doc references a test removed at retirement (Auditor 3, Class C-2, non-blocking)

- **Where:** `docs/V2B_ACQUISITION.md:54`, bound to the same accepted SHA-256 as E-2.
- **Observation:** a present-tense reference to `tests/test_v2b_acquire_workflow_security.py`,
  which was intentionally removed when the one-shot acquisition workflow was retired (confirmed
  absent from the tree; only an orphan compiled `.pyc` remains under the git-ignored
  `tests/__pycache__/`, which is not a tracked artifact).
- **Why it does not invalidate anything:** the workflow retirement is otherwise honestly
  recorded (the governance amendment distinguishes the historical state from the final-tree
  state; no committed workflow contacts the exchange or grants a write capability; the acquire
  sentinel is consumed). The independent acquisition audit passes. The reference is stale text
  only.
- **Disposition:** recorded here; **not** corrected in place (immutable accepted document).

## E-4 — Moratorium "unforgeable" docstring overclaim (Auditor 4, Class C, corrected forward)

- **Where:** `src/eth_research/v2ab/moratorium.py` (module + class docstrings around the
  `_REPLAY_SENTINEL` construction guard). This is **verifier source**, not an immutable
  accepted result or a frozen artifact.
- **Observation:** the docstrings described the `HistoricalReplayAuthorization` token as
  "unforgeable" / stated the token "cannot be forged". Because `_REPLAY_SENTINEL` is a
  module-level object, a determined in-process caller who imports the private sentinel could
  construct the token directly; "unforgeable" overclaims.
- **Why it is not a bypass:** `guard_operation` refuses **every** forbidden
  new-candidate-research operation *unconditionally*, before any token is consulted — the
  auditor forged a token via the sentinel and every forbidden operation was still refused. The
  token only ever gates ALLOWED replay/verify of an already-committed historical experiment,
  and each such replay must additionally match the committed experiment id, the committed
  partition fingerprint, and the accepted package version. No forbidden operation is enabled by
  a forged token.
- **Disposition:** corrected **forward** (a new descendant commit on the V2B acceptance branch)
  by softening the docstrings to state the accurate guarantee: the sentinel is a pragmatic
  in-process barrier (not cryptographic), and the moratorium's strength is the unconditional
  refusal of forbidden operations regardless of any token. No moratorium behaviour, artifact,
  result, or hash changed — a docstring-only edit to verifier source.

---

## Observational (non-defect) items recorded for completeness

These were noted by Auditor 1 as observations, not defects. None invalidates any run and none
is applied retroactively:

- **PR-C1 — walk-forward transitive binding.** `research/m3a/walk_forward_protocol.json` is
  bound to the V2A governance chain transitively (no explicit WF fingerprint field in the
  pre-registration). Not exploitable: the protocol pins rows = 2221 and folds = 5 and the
  walk-forward structure is otherwise fixed and reconstructible.
- **PR-C2 — aggregate-Sharpe fold-seam.** An aggregate-Sharpe presentation detail at fold
  seams; the primary decision statistics and gates are unaffected.
- **PR-C3 — cosmetic assert.** A cosmetic assertion; no behavioural effect.
- **Unused `walk_forward_protocol_v2.json`.** Present but not on the accepted decision path.

---

## Attestation

- No immutable accepted artifact is edited by this register. Entries E-1, E-2, and E-3 annotate
  immutable documents by their accepted SHA-256 and leave them byte-unchanged.
- Entry E-4 is a forward docstring correction to verifier source; it changes no result, no
  fingerprint, no sealed ledger, and no moratorium behaviour.
- The three sealed access ledgers (`research/m3a/development_gate_access.jsonl`,
  `research/m2b/test_evaluations.jsonl`, `research/m3d/prospective_evaluations.jsonl`) remain
  byte-empty. Every V2A and V2B result and registry event is unchanged. Neither nomination
  decision is altered; both remain **no candidate nominated**. The V2 package is **not
  sell-ready**.
