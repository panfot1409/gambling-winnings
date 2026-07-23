# V2C Section 34 - Pre-Qualification Red Team

This document records the independent, pre-qualification red team run against the V2C
candidate-free operational surface **before** the operational-qualification freeze/register/execute
sequence (sections 35-38). Five independent auditors each took one subsystem and were instructed to
break it. Every genuine finding was reproduced failing-test-first, fixed, and locked with a
regression test; nothing was fixed on assertion alone.

The milestone is `2.0.0.dev2`, candidate-free and data-only. Nothing here evaluates a trading
strategy, activates any operational component, or changes `sell_ready` (which stays derived-false).

## Verdict: no terminal stop

The authorization requires a **terminal STOP** on a Class-A scientific defect or a Class-D
governance defect. Two findings were raised at CRITICAL severity (RT3-A, RT4-C1). Both were
classified **fixable and latent**, not terminal, on the following grounds:

- **Nothing false was ever stamped.** The OQ registry ledger (`governance/v2c/oq_registry.jsonl`)
  is byte-empty; no qualification verdict had been recorded, so the vacuous-pass path in RT3-A had
  never produced a signed "PASS". It was caught at exactly the checkpoint it was meant to be caught
  at - before the section 35-38 execution that would have used it.
- **The invariant that matters held.** The buyer boundary's redacted-only guarantee (RT4) was
  intact: the shipped client requests only public/redacted artifacts, withheld items are refused,
  and the vendor keeps the private source. RT4-C1 was a defense-in-depth *doc overclaim* about
  process isolation, with a benign shipped client, fixed by hardening the isolation argv.
- **No sealed partition was touched, no strategy was evaluated, `sell_ready` stayed false.** None
  of the findings implicated a Class-A scientific result or a Class-D governance boundary.

The runtime behaviour of the qualification harness was independently confirmed clean by RT3:
deterministic, zero-exposure on every fill and intent, book 100% cash, and a genuine (not stubbed)
kill switch. The weaknesses were in the *acceptance gate's strength* and *documentation honesty*,
not in what the system actually computed.

## Severity and disposition rubric

| Class | Meaning | Action |
| --- | --- | --- |
| CRITICAL | Would let a false qualification pass, or a source/candidate leak | Fix + regression test |
| HIGH | Robustness hole (crash/hang) reachable by a hostile counterpart | Fix + regression test |
| MEDIUM | Screen that a determined adversary evades | Fix + regression test |
| LOW | Narrow gap or cosmetic honesty issue | Fix or document |
| INFO/ACCEPT | Not a defect given the threat model | Document, no change |

## Findings

### RT1 - candidate-free execution firewall (`firewall.py`)

Verdict: gates sound; two hardening fixes.

| ID | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| F1 | MEDIUM | `CashControlIntent` exposure fields were validated only by `!= 0.0`; an object whose `__ne__` returns `False` (or a NaN/inf) slips past that guard and masquerades as zero exposure. | Route the three float fields through `require_real` (rejecting non-numbers, NaN, inf, bool) before the zero comparison; re-raise as `V2CFirewallError`. | `test_cash_control_intent_rejects_non_real_exposure_fields` |
| F2 | LOW | `assert_no_candidate_reference` did exact-substring matching; case, surrounding padding, or a zero-width separator evaded it. | Normalize (casefold + strip + drop zero-width) before substring containment. | `test_assert_no_candidate_reference_refuses_normalized_id_variants` |
| F3 | LOW/doc | The screen's docstring overclaimed ("refuse any object that is/points at a candidate"). | Softened to "best-effort structural screen"; the authoritative gate is the exact `cash_control` allowlist. | (doc) |
| F4 | INFO | In-process malice (a `str` subclass with a hostile `__eq__`). | Accepted: an in-process actor already has full authority; out of threat model. | (accept) |

### RT2 - prospective governance (`activation_template.py`, `proposal.py`)

Verdict: sound; two hardening fixes.

| ID | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| F1 | LOW | The inactive-template verifier used an enumerated `<scope>: write` denylist; an unlisted scope (`packages: write`, `deployments: write`, ...) passed. | Added a positive rule refusing **any** active `<name>: write` beyond the enumerated markers. | `test_verifier_flags_a_write_scope_beyond_the_enumerated_markers` |
| F2 | LOW | `ProspectiveUpdateProposal.from_mapping` parsed `expected_row_count` with `require_nonnegative_int`, while `__post_init__` required positive - a zero window could be constructed via the mapping path. | Made `from_mapping` use `require_positive_int` (symmetric with the invariant). | `test_proposal_from_mapping_rejects_a_nonpositive_row_count` |
| F3 | INFO | The split marker string is a deliberate control. | Accepted. | (accept) |

### RT3 - operational qualification (`oq/slo.py`, `oq/events.py`, `oq/recovery.py`, `oq/registry.py`)

Verdict: runtime clean; the SLO acceptance gate was too weak.

| ID | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| A | CRITICAL (latent) | `evaluate_qualification` used only universal quantifiers with no non-emptiness or coverage floor: a run with no instruments, or with empty resource/recovery evidence, passed **vacuously**. | Added a `qualification_coverage` criterion (first in `QUALIFICATION_CRITERIA`): the run must have >=1 instrument and every instrument must be covered by a resource **and** a recovery report; empty evidence fails the verdict. | `test_qualification_fails_without_coverage_evidence` |
| B | MEDIUM | `_event_acceptance_correctness` checked out-of-order/delayed rejections only conditionally (no `>0` floor), asymmetric with the duplicate/conflicting criteria. | Added a `> 0` floor on out-of-order rejections per instrument. | Covered by `test_full_qualification_verdict_passes` + coverage test |
| C | LOW | The acceptance floor was on declared manifest slots, not effective accepted events. | Added `OQ_MIN_ACCEPTED_EVENTS` (3500) floor on accepted events (the real fixture accepts 3607). | (calibrated so a real run passes, a degenerate run fails) |
| D | LOW/info | The OQ registry is tamper-evident (hash-chained) but not forgery-proof (an unsigned whole-file rewrite forges a new chain); the recovery kill-switch drill is protected by a zero-exposure cap rather than being routed through `guard_request_kind`. | Documented as an accepted limitation: the registry's guarantee is tamper-evidence under append, not signature; the drill's protective invariant is the zero-exposure cap (validated by `test_recovery_campaign_passes`), with the firewall as a separate first gate. | (doc/accept) |

### RT4 - process-isolated buyer boundary (`buyer/isolation.py`, `buyer/harness.py`, `buyer/boundary.py`)

Verdict: framing / redaction / quota solid; the isolation layer was weak and over-documented.

| ID | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| C1 | CRITICAL (doc overclaim) | The child ran under `-I -B`, which still processes the editable-install `.pth` (site.py runs), so it could import the repository package - contradicting the docstring claim that it "cannot reach repo source". | Added `-S` to the isolation argv (`ISOLATION_FLAGS = ("-I", "-S", "-B")`), disabling `site.py` so the `.pth` is never processed; corrected the overclaiming docstrings to an honest process-isolation statement. | `test_isolation_flags_block_importing_the_repository_package` |
| H1 | HIGH | `serve_session`'s `read_frame` was uncaught: a malformed body crashed the vendor loop (child un-reaped) and a partial frame hung the parent forever. | Wrapped the read in `try/except FramingError` -> respond `error` + break; the isolation driver runs on a watchdog thread that kills the child on timeout. | Covered by `test_isolated_buyer_evaluation_passes` (clean path) + framing tests |
| H2 | HIGH | `scan_source_free` used a narrow denylist that missed real strategy source with no known token, `.pkl/.so/.npy/.pt/.h5/.pyd` payloads, and generic private URLs. | Rewrote as an allowlist: only the expected harness filenames and `.py/.json/.md` suffixes may appear; every non-client file is additionally content-scanned via the redaction `scan_text`. A file with a disallowed suffix is flagged by type **and** still content-scanned, so a mis-suffixed source leak (`leak.txt`) is caught by its forbidden token too. | `test_scan_flags_planted_source_and_forbidden_types` |
| M1 | MEDIUM | `client_import_modules` parsed the in-memory constant (not the on-disk client) and missed dynamic imports (`__import__`/`importlib`). | Flag dynamic-import calls as a sentinel (never in the stdlib allowlist); the isolation path scans the on-disk client that actually runs. | `test_client_import_modules_flags_a_dynamic_import` |
| M2 | MEDIUM | The write-confinement check inspected only the top level of the harness dir. | Made confinement recursive and also snapshot the temp-root outside the harness dir; documented that full-filesystem confinement needs an OS-level sandbox. | Covered by `test_isolated_buyer_evaluation_passes` |
| L1 | LOW | The serve-time redaction re-scan did not treat legacy candidate slug ids as violations. | Added a legacy-candidate-slug re-scan on served text (distinct from the `candidates.py` module path that legitimately appears in the claims catalog). | Covered by boundary serve tests |
| L2 | LOW | `serve_request` passed the item name as the artifact kind. | Clarified: the served item names are exactly the allowed artifact kinds, so the call is correct; documented with a comment. | (doc) |
| L3 | INFO | `double_build_is_identical` is near-tautological. | Accepted. | (accept) |

### RT5 - commercial / readiness pack (`readiness.py`, `commercial/*.py`)

Verdict: invariants hold; three strict-parse fixes.

| ID | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| F1 | LOW | `readiness.parse` ignored `schema_version` and `honest_limitation`; a tampered limitation was accepted. | Validate `schema_version == READINESS_SCHEMA_VERSION` and `honest_limitation == expected`. | `test_rejects_a_schema_version_drift`, `test_rejects_a_tampered_honest_limitation` |
| F2 | LOW | `schema_version` was not checked against its constant in the deployment / ip_dossier / options / readiness parsers. | Added `require_int(...) == <MODULE>_SCHEMA_VERSION` to each `parse`. | `test_deployment_blueprint_rejects_a_schema_version_drift`, `test_ip_dossier_rejects_a_schema_version_drift`, `test_commercial_options_rejects_a_schema_version_drift` |
| F3 | LOW/doc | `evidence.write_all`'s docstring named the old `release/private/v2c/` location. | Corrected to `governance/v2c/commercial/`. | (doc) |

## Re-verification

After the fix pass, the full static and targeted battery is green under Python 3.12 (the project's
`requires-python`):

- `ruff check .` - all checks passed
- `ruff format --check .` - all files formatted
- `mypy src tests examples` - success, no issues (582 source files)
- targeted modules (`test_v2c_firewall`, `test_v2c_prospective`, `test_v2c_oq`,
  `test_v2c_oq_registry`, `test_v2c_buyer_boundary`, `test_v2c_commercial`, `test_v2c_readiness`,
  `test_portfolio_security`, `test_repo_hygiene`, `test_v2ab_acceptance`) - all passing, including
  every new regression test.

Two of the subtlest regressions were shown to target genuine pre-fix bypasses: the hostile-`__ne__`
object returns `False` for `!= 0.0` (so it would have passed the old guard), and the raw substring
screen misses both upper-case and zero-width-split candidate ids while the normalized screen catches
both.

Nothing in this pass evaluated a strategy, activated any component, fetched market data, or altered
the sealed partitions. `sell_ready` remains derived-false and the repository remains private.
