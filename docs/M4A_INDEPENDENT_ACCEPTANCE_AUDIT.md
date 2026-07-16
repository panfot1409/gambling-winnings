# M4A Independent Acceptance Audit (pre-M4B §3 gate)

**Purpose.** Milestone 4B §3 requires that the accepted Milestone 4A release candidate be
**independently re-audited before any M4B work branches from it**, that any Class B/C defect be
fixed *on M4A* (failing-test-first), that stale source-freeze artifacts be regenerated, and that a
**corrected final M4A head** be established from which M4B then branches. This document records that
audit: the method, the findings, their classification against the M4B §47 hard-stop taxonomy, the
disposition, and the evidence that no accepted output, sealed ledger, or public surface drifted.

This is a governance/engineering hardening audit of the *release-candidate platform surface*
(config parsing, the CLI error taxonomy, the governed-output guards, the source-level security
firewall, and the distribution scanner). It is **not** a re-execution of any accepted financial or
scientific result, and it changes **no** accepted output.

- Audited head (accepted M4A): `50d96ebdb66e7513e2253f99e0fb83756d4c5e3f`
  (branch `claude/m4a-offline-research-platform-rc`, PR #10, draft/open/unmerged).
- Base of the M4A stack (accepted M3F): `e231359a1d2f21b490cf5c431b15d731aed7f4ad`.
- Corrected final M4A head: **the single hardening commit that carries this document** (stacked
  directly on `50d96eb`; see "Disposition & corrected head" below). M4B branches from that commit.

---

## 1. Method

Three independent read-only auditors examined disjoint slices of the accepted M4A surface,
each instructed to find the *worst* reachable defect in its slice and to treat governance and
supply-chain integrity as adversarial:

| Auditor | Slice |
| --- | --- |
| Auditor 1 | CLI command handlers, governed-output guards, and the source-level security firewall (`cli/app.py`, `tests/test_m4a_security.py`) |
| Auditor 2 | Public API config parsing and the error taxonomy (`api/config.py`, `api/orchestrate.py`, `api/errors.py`) |
| Auditor 3 | Distribution / packaging integrity gate (`tools/scan_distribution.py`, wheel/sdist allowlists) |

Every finding was then **reproduced as a failing test first** (the test fails against the
accepted `50d96eb` source and passes only after the fix), so the regression suite encodes the
defect, not merely the fix. Reproductions live in `tests/test_m4a_acceptance_hardening.py`
(new) and `tests/test_m4a_security.py` (extended firewall matcher).

---

## 2. Findings

All findings are **Class B** (a governance-authorization / input-taxonomy / supply-chain-tooling
defect that never touched an accepted output) or **Class C** (a defensive-hardening or
verification-strengthening improvement). None is Class A (affecting an accepted financial or
scientific output) or Class D (a confirmed compromise of sealed or accepted state). See §3 for
the classification argument.

### Auditor 1 — CLI, governed-output guards, security firewall

| ID | Class | Defect | Fix | Failing-first test |
| --- | --- | --- | --- | --- |
| **F-A** | B | `_reject_governed_output` anchored its governed-root search to `Path.cwd()`, not to the *resolved output path*. A run launched from **outside** the repository whose `--output` lands inside this repo's governed `research/` tree was **not** refused. | Anchor the search to the resolved output (`_governed_output_roots(resolved)`). | `test_reject_governed_output_anchors_to_output_not_cwd` |
| **F-B** | B | `cmd_dataset_build` never called the governed-output guard at all, so `dataset build --output research/m2b/…` could write a canonical dataset **into a governed root**. | Call `_reject_governed_output(Path(args.output))` at the top of `cmd_dataset_build`. | `test_cli_dataset_build_into_governed_research_is_refused` |
| **F-C** | C | The source firewall scanned only a *hand-listed* set of runtime dirs/files; it did not prove the property over the **entire transitive first-party import closure** (which pulls in accepted governance modules such as `gitcheck`/`ledger`). | Added `test_full_import_closure_first_party_reaches_no_network_client`: import `eth_research.api` + `eth_research.cli.app`, then AST-scan every reachable first-party module for a network/exchange/wallet-client import. It **proves none exists** (the `socket`/`urllib` in `sys.modules` come only from pandas/pyarrow). No production change — the property already held; the test now proves it over the whole closure. | `test_full_import_closure_first_party_reaches_no_network_client` (in `test_m4a_security.py`) |
| **F-D** | B | An over-large `split.context_bars` surfaced as a bare `ValueError`, which the CLI mislabels as an **internal crash (exit 70)** rather than caller input. (Same underlying defect independently found by Auditor 2 as A-A2(b).) | `_context_for` helper translates `ValueError`/`TypeError` → `DatasetError` (exit 4). | `test_cli_oversized_context_bars_uses_dataset_exit_code` |
| **F-E** | B | The firewall's AST matcher missed dynamic-execution spellings: `runpy`, `importlib.util.spec_from_file_location`, `os.exec*`/`os.spawn*`, and `from runpy import run_path`. | Extended `_FORBIDDEN_IMPORTS`, `_FORBIDDEN_ATTR_CALLS`, `_FORBIDDEN_FROM_IMPORTS`; added a `_NETWORK_CLIENT_IMPORTS` subset for the closure scan. | `test_firewall_matcher_catches_dynamic_execution` (parametrized) |

### Auditor 2 — public API config parsing & error taxonomy

| ID | Class | Defect | Fix | Failing-first test |
| --- | --- | --- | --- | --- |
| **A-A1** | B | `config.strategy` and `config.costs` objects did **not** enforce exact keys (the other config blocks do). An unknown key such as a plausible `costs.fee_rate` or `strategy.leverage` override was **silently dropped**, while the receipt's `config_sha256` still attested to the bytes that contained it — a silent-divergence hazard. | `_exact_keys(...)` on both `config.strategy` (`{kind, params}`) and `config.costs` (`{scenario}`). | `test_config_costs_rejects_unknown_key`, `test_config_strategy_rejects_unknown_key` |
| **A-A2** | B | Several config-range errors leaked as an **internal crash (exit 70)** instead of the input taxonomy: (a) non-positive `dataset.file.interval_seconds`; (b) over-large `split.context_bars` (= F-D); (c) `split` fractions out of `(0,1)` or summing `≥ 1`. | Validate in-parser: `interval_seconds > 0` and the split-fraction ranges raise `CanonicalError` → `ConfigurationError` (exit 3); `context_bars` over-run raises `DatasetError` (exit 4) via `_context_for`. | `test_cli_nonpositive_interval_uses_config_exit_code`, `test_cli_bad_split_fractions_use_config_exit_code`, `test_cli_oversized_context_bars_uses_dataset_exit_code` |
| **A-A3** | B | `receipt verify` lacked the canonical-form re-serialization fixed-point check that `result verify` already performs. A **reformatted-but-valid** receipt (re-indented / reordered keys, same content, trailing newline) verified **clean** — it printed "verified against the supplied artifacts" and exited 0. | Add the symmetric guard: `if receipt.to_json_bytes() != receipt_raw: raise ReceiptVerificationError(...)`. | `test_receipt_verify_rejects_noncanonical_receipt` |

### Auditor 3 — distribution / packaging integrity

| ID | Class | Defect | Fix | Failing-first test |
| --- | --- | --- | --- | --- |
| **B-1** | B | The wheel `.dist-info/` allowlist admitted the **entire directory unconditionally**, so a `license-files` glob / metadata hook could smuggle a data file into `dist-info/licenses/…` past the private-data gate. | Restrict admitted `.dist-info/` members to the exact metadata basenames `{METADATA, WHEEL, RECORD, entry_points.txt}`. | `test_scanner_flags_data_file_smuggled_in_dist_info` |
| **B-2** | C | The scanner detected case-collisions but not **exact-duplicate** member names — a zip/tar-confusion / supply-chain-ambiguity hazard. | Track a `seen_exact` set and flag `duplicate member path`. | `test_scanner_flags_exact_duplicate_member` |

---

## 3. Classification against the M4B §47 hard-stop taxonomy

The M4B mandate (§47) enumerates the conditions that force a milestone halt. Two are potentially
relevant here — "an M4A **Class-A** defect affecting an accepted output" and "**any Class D**
confirmed" — and both are **excluded** by evidence, so **no hard stop applies**. The mandate is
explicit that "ordinary software defects are not hard stops," and §3 supplies the exact mechanism
used here: *fix Class B/C on M4A, failing-test-first, regenerate stale freeze artifacts, establish a
corrected head, then branch M4B.*

**Why none is Class A (accepted-output-affecting).** Every fix is confined to input validation, the
CLI error taxonomy, governed-output authorization guards, the source-level firewall, and the
distribution scanner. **No accepted financial or scientific computation changed.** The accepted
single-asset engine and its supporting numerics are byte-for-byte untouched:
`git diff` over `src/eth_research/fractional/`, `accounting.py`, `cost_model.py`, `solver.py`, and
`metrics.py` is **empty**. No `result.json`, `receipt.json`, registry, report, or dataset artifact
is in the change set.

**Why none is Class D (confirmed compromise of sealed/accepted state).** Class D is reserved for a
defect that *actually* compromised sealed or accepted state. The three sealed governance ledgers
are byte-empty and unchanged
(`sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` for all of
`research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`,
`research/m3d/prospective_evaluations.jsonl`). The governed-output findings (F-A/F-B) were
demonstrated only against **synthetic** temp-repo fixtures with a planted file; no real governed
artifact was ever written or drifted. M4A's own accepted red team classified the *identical*
governed-output-guard weakness (its finding F3) as **Class B** and fixed it on M4A — this audit is
consistent with that accepted precedent.

**Conclusion.** All ten findings are Class B/C. The correct disposition is to fix on M4A and branch
M4B from the corrected head — **not** to halt.

---

## 4. Disposition & corrected head

All fixes are delivered as a **single hardening commit stacked on `50d96eb`** (no history rewrite,
no force-push, no tag, no retarget — consistent with the M4B "not authorized" list). That commit
contains, and only contains:

- the source fixes (`api/config.py`, `api/orchestrate.py`, `cli/app.py`);
- the distribution-scanner fixes (`tools/scan_distribution.py`);
- the extended firewall matcher + whole-closure network-client proof (`tests/test_m4a_security.py`);
- the failing-first regression module (`tests/test_m4a_acceptance_hardening.py`);
- the regenerated source-freeze artifact `research/m4a/distribution_manifest.json` (the shipped
  `.py` member hashes moved because three source files changed — regenerated deterministically with
  `python -m eth_research.m4a.release --write`; `--check` is clean);
- this document.

That commit is the **corrected final M4A head**. M4B branches from it.

---

## 5. No-drift evidence

| Invariant | Check | Result |
| --- | --- | --- |
| Accepted financial engine unchanged | `git diff` over `fractional/`, `accounting.py`, `cost_model.py`, `solver.py`, `metrics.py` | empty |
| Public API surface unchanged | `python -m eth_research.m4a.public_api --check` | current (byte-identical snapshot) |
| CLI `--help` surface unchanged | `python -m eth_research.m4a.cli_reference --check` | current (byte-identical reference) |
| Sealed ledgers empty & unchanged | `sha256sum` of the three ledgers | 3 × `e3b0c44…7852b855` |
| Release-candidate freeze consistent | `python -m eth_research.m4a.release --check` | current (only `distribution_manifest.json` regenerated) |
| No accepted result/receipt/registry/dataset touched | change-set review | confirmed |

Because the public-API and CLI-reference snapshots are **byte-unchanged**, the hardening is
strictly internal/behavioral (stricter validation, correct error taxonomy, tighter guards) and is
**additive-compatible** with the accepted v1.0.0 public contract — it neither adds nor removes a
public signature, field, or `--help` line. Every fix only *narrows* what the platform accepts
(rejecting previously-silently-mishandled bad input) or *tightens* a supply-chain/firewall check;
no previously-valid, well-formed input changes behavior.

---

## 6. Verdict

**M4A is accepted, with the Class B/C hardening above applied on-branch.** No M4B §47 hard stop is
present. The corrected final M4A head (the commit carrying this document) is established, green, and
ready for the M4B milestone to branch from it.
