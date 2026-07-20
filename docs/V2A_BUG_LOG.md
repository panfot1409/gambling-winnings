# V2A Bug Log

Append-only record of defects found and fixed during V2A. Each entry gives the finding, its
classification, the fix, and the regression test that locks it in.

Classification (V2A hard-stop taxonomy):

- **Class A** — scientific / financial integrity (would corrupt the one-shot research result). HARD
  STOP; never fixed silently.
- **Class D** — sealed-partition or governance breach. HARD STOP.
- **Class B / C** — correctness / defense-in-depth / honesty hardening that does **not** touch a
  sealed partition or change any pre-registered scientific quantity. Fixed forward.

No Class A or Class D defect has been found. Every entry below is Class B or Class C and was fixed
forward without touching a sealed partition, an accepted engine, or any pre-registered fingerprint
(protocol / candidate / constitution / contract / claims / scorecard / factsheet fingerprints are
unchanged by all fixes here).

---

## §29 — Pre-registration red team (four independent auditors)

Four independent read-only auditors reviewed the frozen V2A surface **before** registration and the
one-shot run. All four confirmed **no Class A/D hard stop** — the governed run is safe to proceed on
integrity and governance grounds. The Class B/C findings below were reproduced and fixed forward.

### Governance / registry / replay (Auditor 2)

| ID | Class | Module | Finding | Fix | Test |
|----|-------|--------|---------|-----|------|
| F1 | C | `v2/registry.py` | Append was a read-check-write without an OS-level lock; two concurrent appenders could both pass the single-run budget check (TOCTOU). | Wrap read+check+write in an exclusive `flock` (`_exclusive_lock`), with `fsync` of file and directory. | Exercised by the existing registry lifecycle/budget/tamper tests; lock is defense-in-depth (no deterministic concurrency test). |
| F2 | C | `v2/replay.py` | Publication/registry consistency was inferred from file existence, not derived from the registry. | `_check_published_run` now derives the expectation from the registry: a completed event **must** have published results, and published results **must** be backed by a within-budget completed event. | `test_v2a_replay.py::test_check_published_run_flags_completed_without_results` |
| F3 | C | `v2/replay.py` | A registry-bypassing publication (results present, no completed event) was not explicitly rejected. | Same rewrite as F2 — the converse mismatch is now a problem; the real run in §31–32 exercises the positive path. | as above (negative case); §31–32 (positive case) |
| F4 | C | `v2/registry.py` | Lifecycle (a terminal event requires a prior `started` for the same run; ≤1 terminal per run) was checked only on append, not on read. | Added `_assert_lifecycle` to `read_events` so a hand-tampered ledger that violates lifecycle is rejected on read. | `test_v2_results_registry.py::test_registry_completed_without_started_is_refused` |
| F5 | C | `v2/registry.py`, `v2/publication.py` | Writes were not durably flushed; a crash mid-write could leave a torn ledger/results file. | `fsync` on append; publication now stages both files (`_stage` + `fsync`), `os.replace`s them into place, then `fsync`s the directory. | Existing publication round-trip tests; durability is defense-in-depth. |

### Buyer boundary — redaction & drift (Auditor 4)

| ID | Class | Module | Finding | Fix | Test |
|----|-------|--------|---------|-----|------|
| B1 | C | `buyer/redaction.py` | Source smuggled *inside* a JSON string value evaded the line-anchored source detector (escaped newlines sit on one physical line). | Added `_scan_json_string_values`: decode JSON and scan every string value standalone; wired into `scan_artifact`. | `test_buyer_boundary.py::test_scan_artifact_catches_source_smuggled_in_json_values` |
| B2 | C | `buyer/redaction.py` | Credential-assignment detector missed `credential`/`auth_token`/`session_token`/`passphrase`. | Broadened the `credential_assignment` alternation. | `test_scan_detects_secrets` (parametrized fixtures) |
| B3 | C | `buyer/redaction.py` | Bare assignment / `return` / `lambda` expression source was not treated as embedded source (threshold too lax). | Added assignment/`return`/`lambda` tokens; threshold lowered to a single marker. | `test_scan_detects_embedded_source`, B1 test |
| B4 | C | `buyer/redaction.py` | The private-key detector source literal itself tripped the repo's private-key hygiene scan. | Rewrote the PEM header pattern with `-{5}` so the detector source is clean while still matching a real header. | repo `test_repo_hygiene.py` (clean tree) |
| C1 | C | `buyer/scorecard.py` | `parse` accepted a well-formed but drifted scorecard. | `parse` re-asserts `fingerprint() == current().fingerprint()`. | `test_buyer_boundary.py::test_scorecard_parse_rejects_drift` |
| C2 | C | `buyer/factsheet.py` | `parse` accepted a well-formed but drifted factsheet. | `parse` re-asserts against the fixed build (which re-binds the live source fingerprints). | `test_buyer_boundary.py::test_factsheet_parse_rejects_drift` |
| C3 | C | `buyer/gateway.py` | A supplied contract with an emptied `withheld` set could weaken the gateway's refusals. | `open` refuses a contract whose fingerprint drifts from the fixed one (defense in depth atop `_texts` holding only scanned artifacts). | `test_buyer_boundary.py::test_gateway_refuses_a_drifted_contract` |

### Scientific coherence (Auditor 1) — no Class A; all Class C coherence/defense

| ID | Class | Module | Finding | Fix | Test |
|----|-------|--------|---------|-----|------|
| Sci-C1 | C | `v2/evaluator.py` | The reused fold-stratified bootstrap fixes a 95% (2.5/97.5) interval, but the protocol independently declares `bootstrap_confidence`; a drift would mislabel the reported CI. | `summarize_candidate` refuses a protocol whose `bootstrap_confidence != M3C_BOOTSTRAP_CONFIDENCE` (0.95). No accepted engine is reparameterized. | `test_v2_evaluation.py::test_summarize_refuses_protocol_confidence_mismatch` |
| Sci-C2 | C | `v2/candidates.py` | The vol-scaled candidate's 30-day / 50%-annual target lives inside the reused overlay; a change to the accepted engine's constants would silently redefine the pinned candidate. | `_build_vol_scaled` re-asserts `VOLATILITY_LOOKBACK`/`ANNUAL_VOLATILITY_TARGET` still equal the pinned spec. | `test_v2_candidates.py::test_vol_scaled_builder_rejects_reused_constant_drift` |
| Sci-C3 | C | `v2/evaluator.py` | The bar interval was taken from `index[1] - index[0]` by hand rather than a validated helper. | Use the reviewed `data.schema.frame_interval` (re-checks a ≥2-row DatetimeIndex). Same value; added validation. | existing evaluation suite (real interval unchanged) |
| Sci-C4 | C | `v2/partitions.py` | The firewall docstring overstated the name-level gate as an absolute guarantee. | Softened to state precisely: it gates *names*, not frames; the data-level guarantee is `load_research_train_only`. | docstring only |

### Shadow platform (Auditor 3) — signal-only tooling; all Class C

| ID | Class | Module | Finding | Fix | Test |
|----|-------|--------|---------|-----|------|
| Sh-C1 | C | `shadow/runner.py` | A `ShadowConfig` built without its `create()` factory could carry a live mode. | `run_shadow` re-validates the mode with `require_shadow_mode` at entry (fail-closed). | `test_shadow_platform.py::test_runner_revalidates_mode_fail_closed` |
| Sh-C2 | C | `shadow/adapter.py`, `shadow/runner.py` | Any adapter (including one declaring a live/venue channel) could be driven. | Added a reviewed `NON_ROUTING_CHANNELS` allowlist (`{"paper"}`); `run_shadow` refuses a non-allowlisted channel before the loop. | `test_shadow_platform.py::test_runner_refuses_non_allowlisted_adapter_channel` |
| Sh-C3 | C | `shadow/runner.py` | The docstring promised staleness monitoring, but the runner never invoked `staleness_alert`. | Per-bar staleness check vs the previous bar's close (a warning; it never halts). | `test_shadow_platform.py::test_runner_raises_staleness_warning_between_far_apart_bars` |
| Sh-C4 | C | `shadow/runner.py` | Drawdown was evaluated *after* the rebalance, so a drawdown breach still let one last fill through on the breaching bar. | Evaluate drawdown on the held (pre-trade) mark **before** any exposure; a breach trips the kill switch so the bar holds. Rebalance conserves equity at a single price, so the drawdown value is unchanged — only the same-bar fill is suppressed. The drawdown trip now also emits the same kill-switch alert a risk breach does (previously asymmetric). | `test_shadow_platform.py::test_runner_drawdown_breaker_holds_book_before_fill` |
| Sh-C5 | C | `shadow/journal.py` | `KILL_RESET` / `CHECKPOINT_WRITTEN` are in the vocabulary but never emitted by the single-pass runner, which read as dead code. | Documented that they belong to a longer-lived operator loop and are retained so such journals parse under the same schema. | docstring only |

**Fingerprint neutrality.** None of the above changes any pre-registered artifact fingerprint. The
protocol, the three candidate specifications, the constitution, and the buyer contract / claims /
scorecard / factsheet all fingerprint identically before and after this batch — verified by the
existing round-trip tests, which continue to pass.

---

## §48 — Post-run red team (four independent auditors)

After the single governed one-shot (`run_001`) executed and published (NO candidate nominated), four
independent read-only auditors reviewed the executed run from distinct lenses. **All four returned NO
Class A (scientific/financial) and NO Class D (governance/sealed-partition) finding, and required no
code fix.** Summary:

| Lens | Verdict | Key confirmation |
|------|---------|------------------|
| Scientific integrity | NO CLASS A | Every fingerprint matches the pre-registration; the no-nomination decision is mechanically correct (confirmed 3 ways) and over-determined (each candidate fails 3 of 4 criteria); deterministic within-fold bootstrap; stressed scenario genuinely more punitive; no look-ahead/peeking channel. |
| Governance / one-shot budget | NO CLASS D | Registry is a sound append-only hash chain; budget consumed & irreversible (a 2nd `started` is empirically refused); lifecycle enforced on append AND read; `completed` binds the exact published fingerprint. |
| Sealed-partition firewall | NO CLASS D | Three sealed ledgers byte-empty (`e3b0c442…`); run read only research-train (2221 rows, ≤ 2022-06-21); sealed partitions structurally unreachable. |
| Reproducibility / publication | REPRODUCES EXACTLY | Strict canonical, no wall-clock; manifest/registry binding correct; pure recompute reproduces `6327de21…` byte-for-byte with no side effects; matches the pre-registration fingerprint-for-fingerprint. |

### Class C / observational items (recorded; none invalidate the run; not applied retroactively)

The pre-registration and results are immutable and the evaluation source is frozen at the P commit, so
these are documented (see docs/V2A_FINDINGS.md §3) rather than retro-fitted into a completed run:

| ID | Class | Where | Note |
|----|-------|-------|------|
| PR-C1 | C | pre_registration.json / research/m3a/walk_forward_protocol.json | The walk-forward protocol is bound only *transitively* (no explicit WF fingerprint in the pre-registration). Not exploitable — rows/folds pinned, fold OOS timestamps cross-checked against the fingerprinted research-train, WF file pins the research-train fingerprint; exactly one valid WF protocol exists for this data. A future run should pin an explicit WF fingerprint. |
| PR-C2 | C | evaluator.py `aggregate_sharpe` | Concatenates per-fold marked returns across independent-cash fold seams. Disclosed; gates only `positive_sharpe`, which all three candidates pass — non-decision-pivotal here. |
| PR-C3 | C | decision.py bare `assert isinstance` | Cosmetic type guard, stripped under `python -O`; caller always passes the correct type. |
| PR-obs | NONE | research/m3a/walk_forward_protocol_v2.json | Unused M3A-era artifact (`folds=[]`); the V2A orchestrator loads `walk_forward_protocol.json` and never references `_v2`. Not wired into any V2A evaluation path. |

No Class A or Class D was found; the real one-shot stands as a valid, reproducible, pre-registered
null result. The Class C items are transparency notes for a hypothetical future governed run and do not
change this run's outcome, which is immutable and consumed.
