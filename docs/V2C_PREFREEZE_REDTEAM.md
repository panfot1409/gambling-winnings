# V2C Supplemental Pre-Freeze Red Team (OQ scaffold, before OQ-E2)

Five independent auditors adversarially reviewed the **complete** V2C operational-qualification (OQ)
executable surface — the candidate-free firewall, the virtual-time harness/runner, the SLO model,
the fail-closed orchestrator, the append-only registry and supersession ledgers, the transactional
publication + completion intent, the calculation-free finalizer, the immutable archive + deep
verifier, the independent OQ-Q oracle, and the read-only CLIs + replay CI — **before** the OQ-E2
replacement source freeze locks it in. Each finding below was reproduced against the live code, then
closed with a fix and a committed regression test (or adjudicated as intended behavior).

Lens assignment: **A** safety/scope/firewall · **B** governance/lifecycle · **C** financial-vocabulary
/numerical honesty · **D** oracle independence & acceptance soundness · **E** transactional /
recovery / strict-parse / CLI & CI.

## Clean bill on the non-negotiables (Auditor A, safety/scope)

No path was found to a strategy/candidate callable; no network/broker/exchange/money path; no
real/prospective/sealed-data ingress; no firewall-guard bypass (`guard_request_kind` /
`resolve_operational_target` are exact allowlists; `assert_no_candidate_reference` catches
callables/modules/marked-objects/legacy-ids including zero-width and casefold variants); the buyer
child is stdlib-only with no socket; synthetic events are pure integer math; published evidence is
limited to three vocabulary-screened artifacts (the journal, which carries `equity_after` /
`final_equity`, is never published). End-to-end reconfirmed: 3607 fills, **0** risky fills, **0**
risky intents, turnover **0**, terminal book units **0**, kill switch not tripped.

## Findings and resolutions

| ID | Sev | Finding | Resolution | Regression |
|----|-----|---------|-----------|------------|
| D1 | HIGH | Oracle + deep verifier re-derived zero-exposure only from the four top-level `operational_counts` aggregates; a forged archive with nonzero **per-instrument** counts but a lied (zero) aggregate was accepted "qualified". | Both gates now re-sum the per-instrument counts and require `aggregate == sum`, and require every zero-exposure field zero **per-instrument and in aggregate**. | `test_v2c_oq_oracle.py::test_forgery_per_instrument_nonzero_hidden_by_zero_aggregate_is_refused` |
| B1 | HIGH | Keyless registry chain: a truncation to byte-empty (reads "pristine") could reset the one-shot budget via the orchestrator's `expect_state` gate; a from-scratch re-chain / `failed`→`completed` rewrite verify clean at the module layer. | New ordered gate `no_prior_run_artifacts` refuses register/start over a surviving run archive or completion intent (the common truncation-after-run case); honest docs record that the chain's ultimate anchor is committed git bytes + the archive/intent, and the completed path is defended by the archive verifier + oracle. | `test_v2c_oq_hardening.py::test_register_refuses_over_a_surviving_run_archive` |
| E1 | HIGH | The finalizer re-appended the intent's `verdict`/`evidence_sha256`/`result_bundle_sha256` without reconciling them against the published archive; a corrupt intent could append a `completed` event the archive cannot support, permanently bricking the append-only one-shot run. | `assess` now re-derives verdict + all terminal digests from the on-disk archive bytes and refuses to finalize on any mismatch; the finalizer holds an `O_EXCL` lock across assess-then-append. | `test_v2c_oq_hardening.py::test_finalize_refuses_intent_with_mismatched_verdict` |
| C1 | MED | The forbidden-vocabulary regex was inflection-aware for `returns?` only; every other term (drawdown, profit, benchmark, alpha, equity, sharpe, roi, …) missed its plural/inflected form. | Every term now catches its inflections; the oracle's independent copy matches, locked by a drift test. Benign look-alikes (`alphabet`, `equitable`) still do not match. | `test_v2c_oq_hardening.py::test_forbidden_vocabulary_catches_plurals` |
| D2 | MED | `requested_/approved_risky_exposure` were absent from the oracle's and verifier's zero-exposure field set; a result declaring nonzero approved exposure was accepted. | Both exposures added to the checked set (oracle + verifier); also measured (see L1). | `test_v2c_oq_oracle.py::test_forgery_nonzero_approved_exposure_is_refused` |
| D3 | MED | The oracle drift test used `<=` for the floor and did not cross-check the forbidden-vocab copy; the independent screen could silently weaken. | Drift test now asserts exact equality of the floor and of the forbidden-vocab / zero-exposure / summed-field copies against the source. | `test_v2c_oq_oracle.py::test_oracle_copies_do_not_drift_from_source` |
| B2 | MED | The "OQ-E2 CI terminal-green" gate was a bare caller-supplied bool bound to no commit. | Gate now requires a 40-hex lowercase source-freeze commit and binds the attestation to it; docs state honestly that this is a trusted-CI-caller attestation (no offline CI query is possible) anchored to the frozen source every other gate proves reproduces. | covered by orchestrator suite |
| B3 | MED | Low-level `build_/append_supersession` validated only caller self-reported pristine fields; `_sha256_of` treated a **missing** sealed ledger as byte-empty. | `_sha256_of` now refuses a missing file; docstrings corrected — `record_supersession` is the sanctioned live-state-binding entry point (it reads the live registry + on-disk sealed ledgers). | `test_v2c_oq_hardening.py::test_sha256_of_refuses_a_missing_file` |
| E2 | MED | Completion-intent artifact relpaths were validated only by `startswith(archive_dir)`; a `..` traversal was accepted, letting the finalizer read outside the repo. | Relpaths are validated against the exact set of three known archive relpaths — traversal / out-of-archive is structurally impossible. | `test_v2c_oq_hardening.py::test_completion_intent_refuses_path_traversal_artifact` |
| E3 | MED | `cli.main` and `completion.from_json_bytes` caught only the `V2ValidationError` tree, not the disjoint `M3DValidationError`/`StrictJSONError` tree; a dup-key governance file crashed with a raw traceback. | Both now catch both trees; malformed governance bytes surface as structured JSON / `OQCompletionIntentError`. | `test_v2c_oq_hardening.py::test_completion_intent_dup_key_raises_typed_error` |
| A1 / C3 | LOW | `requested_/approved_risky_exposure` were published as hardcoded `0.0` literals, not measured. | Now measured from the run (sum of fills' target weights; sum of intents' approved weights) so the published evidence proves the invariant rather than restating it. | oracle/verify suites (measured values are 0) |
| A2 | LOW | `risky_fill_count` in the result counted `traded_units != 0` only, disagreeing with the SLO's `traded_units != 0 OR units_after != 0`. | Result definition aligned to include a held-but-not-traded position. | oracle/verify suites |
| D4 | LOW | The verifier's zero check treated JSON `false` as zero (bool-vs-int), looser than the oracle's `_is_zero`. | Verifier now uses a strict `_is_zero` that rejects bools. | `test_v2c_oq_hardening.py::test_verify_archive_strict_zero_rejects_bool` |
| D5 | LOW | The oracle decoded `passed` with `bool(...)`, coercing `"false"`/`1` to a pass. | Strict decode: `passed` must be a real boolean or the criterion is refused. | `test_v2c_oq_oracle.py::test_forgery_non_boolean_passed_flag_is_refused` |
| E5 | LOW | `finalize` took no lock; two concurrent `recover --finalize` could double-append and brick the registry. | `finalize` now holds an `O_EXCL` lock across the assess-then-append critical section. | exercised by the finalize path |
| E4 | LOW | The CI "registry byte-empty" step presented as a guard but only echoed (never `exit 1`). | Reframed honestly as a *report* step; the state-aware replay step is the actual certifier (the registry legitimately becomes non-empty after OQ-R). | `.github/workflows/v2c-replay.yml` |
| E6 | LOW | The CI push `paths:` filter omitted the three sealed-ledger paths whose emptiness the job asserts. | Sealed-ledger paths added to the trigger, so a push touching only a sealed ledger still runs the emptiness check. | `.github/workflows/v2c-replay.yml` |

## Adjudicated — not a defect

**C2 (shadow drawdown/equity computation).** The shadow-operations platform computes a per-bar equity
high-water mark and a drawdown ratio inside `drawdown_alert`. This is **kill-switch machinery** — the
milestone scope (§0) explicitly permits "trip/verify kill switches", and a drawdown-based kill switch
must compute a drawdown threshold to decide whether to trip. It is not a strategy-performance
evaluation: the prohibited item is "drawdown-**as-performance**", i.e. using drawdown to judge
strategy quality or attract a buyer, which this is not. Under the candidate-free cash-control scope
the book holds 100% cash, so the equity is flat and the drawdown ratio is identically zero and the
switch never trips (consistent with the reconfirmed run). The metric never reaches the published
result. The code lives in frozen V2A `src/eth_research/shadow/` and is left unchanged; Auditor A's
independent safety/scope pass did not flag it as a scope violation. Recorded here for honesty: the OQ
operational machinery does compute a drawdown *threshold* internally, distinct from any performance
metric.

## Scope discipline

Every fix is confined to the OQ orchestration surface (`result`, `oracle`, `verify_archive`,
`completion`, `finalize`, `cli`, `orchestrator`, `supersession`) plus tests and the replay workflow.
No fix touched a sealed ledger, a frozen `research/`/`release/` artifact, the shadow platform, or the
canonical OQ registry (which remains byte-empty). All eight modules are captured by the forthcoming
OQ-E2 replacement freeze, which is the correct point to lock the hardened scaffold.
