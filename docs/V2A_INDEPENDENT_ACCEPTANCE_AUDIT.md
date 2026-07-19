# V2A Independent Acceptance Audit (V2B Part I)

Before writing any V2B research-memory, candidate, or acquisition code, Milestone V2B independently
re-audits Milestone V2A as an **immutable accepted base**. Four independent read-only auditors
reproduced the V2A one-shot from committed bytes and attacked its governance from distinct lenses. No
V2A artifact was altered by this audit; every reconstruction and adversarial attempt ran on scratch
copies only.

**Accepted V2A tip:** `d437dafd67047470eae2c88fb14f0d8db6bf7091` (PR #16, draft, unmerged, base `main`).
Audited from `claude/v2b-cross-asset-research-reset` at the §0/§1 head (the pre-V2B version-bump/freeze
and the plan doc touch no `research/**` artifact; `git diff d437daf..HEAD -- research/ examples/` is
empty).

## Verdict

> **V2A NEGATIVE RESULT ACCEPTED AS IMMUTABLE RESEARCH EVIDENCE.**

All four auditors returned **no Class A** (scientific/financial) and **no Class D**
(governance/sealed-partition) finding. The single governed one-shot (`run_001`) nominated no candidate;
that null reproduces byte-for-byte (`results_fingerprint = 6327de21…`), is mechanically correct and
over-determined, consumed the one-shot budget irreversibly, and read no sealed data. V2B proceeds to
new research on this accepted base. V2 remains `not_sell_ready`.

## Auditor A — scientific result → VALID (no Class A)

- Independently re-ran the accepted engine on the real research-train and reproduced every published
  number; all **40** cells (3 candidates + `buy_and_hold`) × {`causal_proxy_base`,
  `causal_proxy_stressed`} × 5 folds are present.

| candidate | folds beat (need ≥3) | primary point | primary 95% CI | lower>0 | stressed robust | Sharpe>0 | status |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|--------|
| `meanrev_zscore_accumulation`    | 2/5 ✗ | −0.001581 | [−0.003952, +0.000789] | ✗ | ✗ | ✓ | research_stage_rejected |
| `vol_scaled_hold_drawdown_guard` | 2/5 ✗ | −0.000396 | [−0.002253, +0.001564] | ✗ | ✗ | ✓ | research_stage_rejected |
| `trend_regime_single_horizon`    | 2/5 ✗ | +0.000145 | [−0.001291, +0.001639] | ✗ | ✗ | ✓ | research_stage_rejected |

- `NOMINATION_CRITERIA` = {≥3 folds, bootstrap lower bound >0, stressed robustness, positive Sharpe}.
  Each candidate fails exactly 3 of 4 (passes only Sharpe) → over-determined rejection;
  `nominated_candidate_id = null`. `decide()` re-run two independent ways yields no nomination.
- No sealed data: `research_train_fingerprint = sha256:60aa988e…`, rows 2221, last open 2022-06-21;
  the three sealed ledgers are byte-empty (`e3b0c442…`). `docs/V2A_FINDINGS.md` makes no
  out-of-sample/forward/live/profit claim. `replay --check` → "V2A replay OK".

## Auditor B — lifecycle / provenance → SOUND (no Class D)

- **E→R→P git ancestry:** R = `98d4f29` (writes `pre_registration.json` only) + fixup `1b45080`;
  P = `0e7b4cb` (adds registry + results + manifest). `R ⊂ P ⊂ HEAD` confirmed; at R the registry and
  results are absent (registered-not-executed), at P all four exist.
- **Registry chain:** `started(run_001, seq0) → completed(run_001, seq1)`; genesis `0×64`;
  `seq1.prev == seq0.entry`; each `entry_hash` recomputes; `completed` binds `results_fingerprint =
  6327de21…`. `verify_registry → []`.
- **One-shot budget (`MAX_RESEARCH_EXECUTIONS = 1`) un-resettable:** appending a second `started`
  (any run_id) → `RegistryError: … one-shot research budget is consumed`; read-side lifecycle rejects
  hand-forged chains with two `started`, a lone `completed`, or a double terminal — while a well-formed
  forged `started→completed` IS accepted, proving the rejection is budget/lifecycle policy, not hash
  breakage.
- **Cross-binding:** `ResearchProtocol.current().fingerprint() = 2854a806… = results.protocol_fingerprint`
  even under the `dev1` bump (V2A's protocol fingerprint is version-independent and
  `V2A_PACKAGE_VERSION` is frozen at `dev0`); `verify_preregistration → []`; results match the
  pre-registration on run_id/protocol/constitution/budget/candidate fingerprints (all 5).
- **Six attacks fail closed:** alternate-path registry (ignored; canonical is authoritative),
  truncated-canonical + stashed-real (rejected), registry/results symlink to foreign bytes (rejected,
  fails closed), protocol/source relabel and committed-fingerprint tamper (drift rejected on multiple
  counts). `verify_publication → []`.

## Auditor C — operations / buyer boundary → SOUND (no Class D)

- Signal-only: the sole concrete adapter is `PaperExecutionAdapter` (channel `paper`; records intents,
  routes nothing); `run_shadow` re-validates a non-live mode and refuses channels outside
  `NON_ROUTING_CHANNELS = {paper}`; **zero** network/exchange/wallet imports anywhere in `shadow/`; no
  `place_order`/`connect`/`api_key`/`sign_transaction`.
- Latching kill switch holds every subsequent bar after a hard breach until explicit reset; the journal
  is an append-only SHA-256 chain, re-run byte-identical, tamper-detecting.
- Redaction: `scan_artifact` flags a bare `def foo(): return 1` as `embedded_source`, and catches source
  smuggled inside JSON string values; the diligence bundle assembles source-free; the gateway serves
  only redacted artifacts and refuses every withheld item and drifted contract.
- `ReadinessScorecard.current()` = `commercial_readiness: absent`, overall `not_sell_ready`;
  `STANDING_POSTURE == "not_sell_ready"`; all claims decode through the constitution with no reserved
  status; `FORBIDDEN_LIVE_MODES` rejected fail-closed; hygiene gate bans network/exchange/wallet
  imports. Authorized suite: 73 passed.

## Auditor D — repository / CI neutrality → SOUND (no Class D)

- `git diff d437daf..HEAD -- research/ examples/` is **empty**; the only changes since the V2A tip are
  the version bump `2.0.0.dev0 → 2.0.0.dev1`, the V2A freeze (`V2A_PACKAGE_VERSION`; orchestrator and
  pre-registration now stamp the frozen constant), the version-test updates, and the docs-only
  `docs/V2B_PLAN.md`.
- Three sealed ledgers byte-empty (`e3b0c442…`). `test_stack_freeze_table` +
  `test_private_reproducibility_contract` + `test_repo_privacy_contract` pass; `replay --check` OK.
- No LICENSE/COPYING; no `license` field/classifier (only `Private :: Do Not Upload`). No 2.0 tag or
  release (`get_release_by_tag v2.0.0` → 404). 14 workflows, all `contents: read` (plus the allowlisted
  `private-release-build.yml` uploader); no `*-acquire.yml`/`*.trigger`; `test_workflow_security` +
  `test_private_workflow_security` pass (57). `docs/V2A_TERMINAL_AUDIT.md` claims cross-check against the
  live repo (sealed hash, `6327de21…`, PR #16 draft, `dev0` frozen, null decision).

## Class C / observational items (recorded; none invalidate V2A; none applied to V2A source)

V2A's committed artifacts and source are immutable and accepted; these observations are recorded here
and, where relevant, folded into **V2B's own** verifier/hardening — never retro-fitted into V2A.

| ID | Class | Where | Note |
|----|-------|-------|------|
| A-C1 | C | pre_registration.json / m3a/walk_forward_protocol.json | WF protocol bound only transitively (no explicit WF fingerprint in the pre-registration). Not exploitable — the WF file itself pins `research_train_content_fingerprint = 60aa988e…`, rows 2221, folds 5. Already disclosed in V2A findings. **V2B pins an explicit WF fingerprint in its pre-registration.** |
| A-C2 | C | v2/evaluator.py `aggregate_sharpe` | Concatenates marked returns across independent-cash fold seams; gates only `positive_sharpe` (non-decision-pivotal). Disclosed in V2A findings. |
| A-C3 | C | v2/decision.py | One bare `assert isinstance` (stripped under `python -O`); caller always well-typed. Disclosed. |
| B-C1 | C | v2/replay.py, v2/registry.py readers | Registry/results readers do not structurally reject a symlink (`120000`) to byte-identical content. Not exploitable — content binding (hash chain + budget + lifecycle + manifest sha + prereg/protocol binding) constrains what can validate, and a committed symlink is visible in git. **V2B's verifier adds explicit symlink refusal.** |
| B-C2 | C | v2/replay.py | A present-but-non-JSON results/manifest raises `StrictJSONError` (a `ValueError`, not `V2ValidationError`) as a traceback rather than a tidy problem string. Still fails closed (`--check` rc=1). **V2B's verifier catches both.** |
| B-C3 | C | v2/orchestrator.py | `run_one_shot(registry_path=…)` override exists but publication always targets the canonical dir and the verifier hardcodes the canonical registry, which append-refuses a second `started`; cannot re-authorize the consumed one-shot. Informational. |

None of the above is a scientific (Class A) or governance/sealed (Class D) defect. V2A stands as a valid,
reproducible, pre-registered **null** result, accepted immutable, and V2B builds forward without touching
it.
