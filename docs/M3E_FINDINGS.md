# M3E Independent Red-Team Findings & Resolution

Three independent, read-only red teams audited the Milestone 3E review-only update
facility from disjoint angles:

- **A — Security / workflow posture / privilege:** every workflow YAML, the
  `_no_unsafe_workflow` scanner, `publisher`/`lease`/`review_policy`, the probe
  entrypoint, and a package-wide search for secrets/network clients.
- **B — Data integrity / two-runner attestation / append-only / replay:** the
  accepted base, cutoff, plan, acquisition, comparison, transition, assembly,
  registry, replay, and the shared canonical-JSON / sha256 / atomic helpers.
- **C — Governance / firewall / claim honesty:** the AST import allow-list, the
  35-check verifier, the status/registry guards, the sealed-ledger checks, and
  every M3E document.

**Headline (all three agree): HEAD is clean.** No live prohibition is violated —
all workflows are `contents: read`, the three sealed ledgers are byte-empty, the
review policy and governance flags are pinned to exact all-false/draft-only
constants, no `m3e` module imports an engine or a network client, and `status`
emits a fixed safe dict. Every finding below is either a *screening-guard
robustness* gap (a substring/marker heuristic weaker than the absolute guarantee
the docs asserted) or a *replay-hygiene* item — not an exploitable bypass, because
the lifecycle deliberately bottoms out at a **draft PR under mandatory human
review** with **no auto-merge**.

The genuine defects were fixed in code (commit 23) with tests; the irreducible
residuals are documented here with their mitigations.

## Fixed in code (commit 23)

| # | Finding (red team) | Fix | Test |
|---|---|---|---|
| F-A | `_no_unsafe_workflow` was substring-only: `permissions: write-all`, an omitted permissions block, quoted/whitespaced `contents: write`, `secrets['X']`/`secrets: inherit`, `upload-artifact`/`upload-pages-artifact`, `git push -f`/`+refspec`, `--auto=`/GraphQL/action auto-merge, and scheme-less `coinbase.com` all evaded it (A1-A4,A6,A7 / B4,B5 / C1). | Rewrote the scanner: it now **requires** an explicit permissions block, rejects `write-all` and any `: write` scope, matches secrets in dotted/index/`inherit` forms, refuses artifact uploads, catches `-f`/`+` force-push and every auto-merge spelling, and matches a bare Coinbase host. | `test_m3e_workflow_security.py::test_hardened_scanner_rejects_each_evasion` (14-case matrix) + `test_a_content_writing_workflow_is_caught` |
| F-B | The forbidden-evaluation-artifact scan (check 35) used a 9-marker name list and never asserted the proposal directory was a **closed** file set, so `runner_a/weights.json` / `returns.json` / a stray dir slipped through (C2). | Expanded the marker vocabulary to the comprehensive strategy/performance set **and** added an exact expected-entry check: the proposal top level must be exactly `{manifest, comparison, transition, runner_a/, runner_b/}`. | `test_m3e_proposal.py::test_a_forbidden_evaluation_artifact_in_the_proposal_is_caught` |
| F-C | The `status` key guard omitted several computed quantities (turnover, drawdown, sortino, calmar, exposure, leverage, …) (C3). | Extended `FORBIDDEN_STATUS_KEY_SUBSTRINGS` to the comprehensive numeric-leak vocabulary. (`evaluation`/count-style words are intentionally excluded — the guard is bool-exempt and `prospective_evaluation_byte_count` is a legitimate int key.) | `test_m3e_cli.py::test_status_guard_rejects_a_numeric_evaluation_quantity` |
| F-D | `_scan_m3e_imports` skipped **relative** imports (`node.level > 0`) and never checked **network/wallet** modules, so `from ..fractional.engine import …` and `import socket` in an `m3e` module evaded the runtime verifier (C4). | The scan now resolves relative imports to absolute paths (mirroring the architecture test) and rejects the network/wallet prefix list. A consistency test locks the verifier's allow-list and network list to the architecture test's. | `test_m3e_adversarial.py::test_injecting_a_relative_engine_import_is_caught` / `::test_injecting_a_network_import_is_caught`; `test_m3e_architecture.py::test_verifier_and_architecture_allowlists_agree` |
| F-E | `assert_draft_only` validated the head strictly but never pinned the **base**, so a descriptor could target `main`/another branch/`""` (A5). | `assert_draft_only` now requires `base == ACCEPTED_COHORT_BRANCH`. | `test_m3e_publisher_e2e.py::test_assert_draft_only_pins_the_base_to_the_accepted_cohort_branch` |
| F-F | The live package version (`0.8.0`) was stamped into replay-bound artifacts, so a later version bump would break byte-exact replay (B2). | Froze `M3E_PACKAGE_VERSION = "0.8.0"` as a literal (byte-identical to what is stamped → replay-neutral), exactly as M3D pins `"0.7.0"`. | `test_m3e_architecture.py::test_m3e_package_version_is_a_frozen_literal` |

## Accepted residuals (documented, mitigated — not fixed in code)

- **R-1 — Completed-day cutoff is not re-asserted against a trusted clock at
  verification (B1, MEDIUM).** `verify_update_proposal` re-derives everything from
  committed bytes but has no notion of "now," so a proposal whose plan claims a
  cutoff one day too far (including the still-forming current-day candle) passes the
  offline 35-check graph. This cannot be closed *offline* — only a clocked step can
  know the current day. **Mitigations, all load-bearing:** (a) the honest tooling
  builds the cutoff correctly (half-open `[first_missing, floor(as_of))`); (b) the
  two-runner attestation catches a forming candle whenever the two fetches differ in
  time; (c) **every** proposal is a draft PR under mandatory human review with no
  auto-merge — a reviewer sees the proposed last-open date. A future hardening is to
  thread a trusted `as_of` from the PR-check workflow's `date -u` and assert
  `completed_day_exclusive_end <= floor(as_of)`; it is recorded here as the
  recommended next step rather than shipped, to avoid a late signature change to the
  un-skippable verifier.

- **R-2 — Two-runner "isolation" rests on a self-reported identity string (B3,
  LOW).** A single actor authoring the proposal PR can write byte-identical raw
  bodies into `runner_a/`/`runner_b/` with distinct `runner_identity` strings and
  satisfy the canonical-equality attestation. This is **by design and already
  documented** (`comparison.py`, `M3E_THREAT_MODEL.md`, `M3E_BUG_LOG.md`): the
  two-runner check is an offline **integrity/reproducibility** control, *not*
  cryptographic authenticity against an external oracle. Future-only candle bytes
  have no offline oracle; the draft-PR + human-review gate is the authenticity
  backstop and must never be relaxed.

- **R-3 — `package_version` in the plan/receipt is `require_str`, not
  `require_exact` (B6, NIT).** It is folded into `plan_sha256` (immutable post-hoc)
  and gates nothing; free-form provenance, left as-is.

## Verified enforced (all three teams, traced in code)

Sealed-ledger byte-empty (exact `byte_count == 0` **and** `sha256 == e3b0c442…855`,
symlink/missing-file safe); review policy and governance flags pinned by **exact
dict equality** plus an `any(bool(v))` guard; M3C candidate still rejected and the
accepted base immutable (byte-exact rebuild, fingerprint `bb6dd392…`,
immature/unauthorized, full M3D program intact); append-only transition (accepted
prefix byte-identical, one-interval seam, no gap/overlap/reorder, `proposed = old +
new`, old fingerprint == base); idempotency domain-separated over five fields;
canonicalization collisions (NaN/Inf/−0.0/dup-keys/overflow) all rejected, and
`content_match` requires **both** fingerprint and rows equal (so a mismatch can only
HARD-STOP); all four committed artifacts rebuilt and byte-compared; transactional
publish with readback + full rollback and a last-written completeness marker;
proposal branch never main/accepted (protected-set + shape guards); the 35 checks
are distinct and count-asserted (no silent skip); the allow-list is identical to the
architecture test's (now consistency-locked). The two-runner attestation is
described honestly and is **not** oversold.
