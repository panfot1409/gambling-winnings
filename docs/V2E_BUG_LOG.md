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
