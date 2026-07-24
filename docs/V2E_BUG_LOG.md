# V2E Bug Log

1. **V2E-001 (C, fixed):** dashboard builder checked sealed ledgers after
   `verify_accepted_base`, so a violated seal surfaced as a byte-mismatch message
   instead of the explicit refusal. Reproduced by `test_nonempty_sealed_ledger_refuses`;
   fixed by checking the ledgers first.
2. **V2E-002 (C, fixed):** proposal ancestry check hashed the accepted-base file bytes,
   but `proposal_manifest.accepted_base_sha256` binds the document's canonical
   `base_sha256`. Reproduced against the real proposal worktree (`779df6bb`); fixed to
   compare the verified `AcceptedProspectiveBase.base_sha256`.
3. **V2E-003 (C, fixed):** manifest has no top-level `proposal_id`; panel now uses the
   proposal directory name.
4. **V2E-004 (C, open, documented):** legacy replay/CI workflows pin the pre-proposal
   state (row_count 3, proposals_recorded 0, genesis fingerprint), so on the PR #22
   merge preview `CI`, `M3D/M3E/M3F Replay` and `V2AB Stack Acceptance Replay` fail even
   though the package-level deep replays pass on the exact proposal tree and the
   dedicated `M3E Update PR Check` is green. Failing evidence: PR #22 check runs.
   Remediation (human-gated, out of V2E scope): make those pins state-aware in the same
   change that merges the first data proposal; V2E adds no new pins of this class.

## Five-auditor review (post-build)

5. **V2E-005 (B, fixed):** `host=""` passed the loopback check but binds ALL interfaces
   (INADDR_ANY) — silent LAN exposure with no opt-in or warning. Reproduced live by
   auditor 2 and by `test_empty_host_is_not_loopback`; fixed by treating only
   `localhost`/loopback IPs as loopback.
6. **V2E-006 (C, fixed):** the visible P&L row label rendered double-escaped
   ("P&amp;amp;L"). Regression `test_pnl_label_is_not_double_escaped`.
7. **V2E-007 (C, fixed):** the header's 40-hex commit could force horizontal scroll at
   phone widths (overflow-wrap was scoped to sections only). Fixed at body level;
   `color-scheme` pinned dark. Regression `test_body_wraps_long_tokens_for_phones`.
8. **V2E-008 (C, fixed):** the "two runners agreed byte-for-byte" line was rendered
   without reading the bundle's `acquisition_comparison.json`; a falsified record now
   refuses the whole build (`test_tampered_runner_comparison_refuses`), and the
   timeline's pending-proposal row no longer asserts unverified external PR state.
9. **V2E-009 (C, fixed):** defense-in-depth from auditor 5 — `requirements` objects are
   type-pinned exactly like the activation token, so a subclass overriding
   `all_satisfied` is refused at minting and at the active transition
   (`test_subclassed_requirements_cannot_lie_via_properties`); OPTIONS/TRACE now get
   the defensive-header 405 path; the status guard also screens string values.
10. **Documented-only (LOW, open):** hardcoded status strings in render.py are backed by
    builder refusals but could drift (auditors 3+4); the strategy poison-spy canary
    covers the donchian module with the import graph as the compensating control
    (auditor 3); token minting should gain provenance binding before any engine ever
    lands (auditor 5); stdlib 501 pages for unknown verbs lack defensive headers
    (auditor 2); no auto-refresh by design (auditor 4).
