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

---

## Process defect P-1 — concurrent writers produced a torn import block

**Class:** process (no defect shipped; two verification results were invalidated).

**What happened.** Three subagents were dispatched in parallel on nominally
disjoint file sets while the primary agent also edited shared source. The
separation held for *deliverables* but not for the *tree*: they shared one
working copy. Three concrete failures followed.

1. **Torn import block.** The §7 (test-assertion) agent observed its own import
   block in `tests/test_m3e_proposal.py` "partially clobbered mid-edit" and had to
   restore it. At one point it reported `src/` was transiently un-importable —
   caught while another agent was mid-way through relocating
   `proposal_authority.py` from `v2e/` to `m3e/`.
2. **Unattributed sweep.** The primary agent ran `git add -A` while the §6
   (dashboard-status) agent was still writing, so that agent's in-flight files
   were committed under a message describing entirely different work. The §6 agent
   independently reported the same event from its side ("another process committed
   my working-tree changes; I ran no git write commands"). Disclosed in the commit
   that followed; content was later verified byte-identical to that agent's final
   state, which was luck, not design.
3. **Two invalidated full-suite runs.** One began against a dirty tree and then had
   HEAD move underneath it mid-run (`1c4a279` → `45cf9d8`); the failure counts it
   produced (3, then 5) carried no information and were withdrawn. A separate
   file-policy test also went red purely because a regenerated registry was
   uncommitted — the policy's own "no uncommitted drift" rule firing correctly on
   the author's own working state.

**Root cause.** Parallelism was scoped by *file ownership* but not by *tree
ownership*. Any writer touching a shared checkout invalidates every concurrent
reader — tests, imports, verifiers, and `git add`.

**Remediation (now binding).** Single-writer discipline:

- only the primary agent may modify files in the shared worktree;
- subagents and auditors are strictly read-only against it;
- all adversarial reproduction happens in scratch overlays, temp dirs or
  disposable clones;
- no subagent runs a formatter against the shared tree, and none applies patches;
- no background task mutates source while another imports or tests it;
- before every commit: confirm no unexpected path changed and that every source
  file still imports;
- stage with explicit paths, never `git add -A`, whenever any other task is live.

**Standing lesson.** A red result obtained from a tree that was moving is not
evidence of a defect, and must be withdrawn rather than reported — three of this
milestone's reds were of exactly that kind.
