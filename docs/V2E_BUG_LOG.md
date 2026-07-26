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

---

## Process defect P-2 — three probes that "caught" nothing

**Class:** process (no defect shipped; three adversarial results were withdrawn
before being reported as evidence).

**What happened.** The first attack matrix written for auditor B's A-5 finding
(the closed proposal file set) reported three of four probes CAUGHT. Reading the
refusal messages rather than the exit codes showed none of them exercised the new
check:

1. **F1** smuggled a file into `runner_a/` and pinned it. Refused by the proposal
   loader's runner-directory shape check — a guard that predates this work.
2. **F2** additionally recomputed the file-set binding to match the lie, but its
   *setup* was refused: the harness edited the record before deriving, and the
   record lives under an allowed root, so the policy's own "no uncommitted drift"
   rule fired. A setup failure is not a probe result.
3. **F3** built a real forged proposal commit. Refused by the existing
   closed-set check over `research/m3e/proposals/<id>/`.

A fourth confound was found later: the compatibility path appeared to catch the
re-chained probes, but its only failures were `09_recovery_capsule` and
`10_recovery_drill` — capsule drift caused by the probe changing bytes, not a
semantic catch at all.

**Root cause.** Two distinct errors. The probes were not *re-chained* past the
guards that already existed, so they never reached the mechanism under test; and
the harness left deterministic derived artifacts stale, manufacturing an
unrelated failure that read as a catch.

**Remediation.** The matrix was rewritten:

- attacks target the m3d side of the proposal, which the pre-existing closed-set
  check does not glob — the one place a pin-is-the-allowlist bug was still
  reachable;
- the smuggled file is committed *before* the binding is derived, so the attacker
  works from a clean tree exactly as a real one would;
- the reseal step now rebuilds the recovery capsule and the drill record too,
  because a competent attacker would;
- every probe is additionally re-run with the new check deleted from the clone's
  source. If the probe still fails, the check was not the guard that caught it.

Under the rewritten matrix all three attacks are caught by all three enforcement
paths, the control passes on all three, and deleting A08 makes all three pass —
so the check is load-bearing rather than shadowed.

**Standing lesson.** A probe is not "caught" because the command exited nonzero.
Read the refusal, confirm it names the mechanism under test, and prove it by
removing that mechanism and watching the probe succeed. Exit codes measure
plumbing; refusal messages and mutants measure the guard.

---

## Reconciliation R-1 — stale open-item labels, and one real defect behind them

**Class:** process finding plus one Class C defect (fixed).

Two findings (C B-3 canonical dashboard status, C B-2 vacuous assertions) were
carried as "open" in a progress report after earlier commits had reported them
closed. Neither account was taken on trust; both were verified from committed
history and by guard-deletion mutants.

| Finding | Fixing commit | Production guard today | Regression test | Guard-deletion mutant | Actual status |
| --- | --- | --- | --- | --- | --- |
| C B-3 canonical status | `0d77cf1` (`src/eth_research/v2e/status.py`) | one `StatusLabels` table; heading, badge, claim, detail and timeline all read from it | `test_v2e_status.py` (36), `test_v2e_dashboard.py` (41) | swap the ACCEPTED and PROPOSED `detail` sentences across records → 3 tests FAIL | **CLOSED, load-bearing** |
| C B-2 vacuous assertions | `0d77cf1` and predecessors | `_proposal_panel` both-ends pin, `src/eth_research/v2e/state.py` | `TestAcceptedProposalEqualsTheAcceptedCohort` | delete the row-count and last-open comparisons → FAIL | **CLOSED, load-bearing** |

Neither fix was lost or torn by the concurrent-writer collision (P-1): all
sources import, all commits from `47c9d65` forward are ancestors of HEAD, and
the tree is formatted.

**A first mutant said "vacuous" and was wrong.** The B-3 mutant initially matched
the first two ``detail="..."`` strings in the file, which are the ``detail`` and
``timeline_detail`` of the *same* ``_PROPOSED`` record — an intra-record shuffle
that changes nothing the tests assert. Recorded here because it is P-2 exactly:
the mutation must be confirmed to be the intended one before its result means
anything. The corrected cross-record swap fails three tests.

### The real defect the reconciliation surfaced (Class C, fixed)

Every load-bearing B-2 test resolved the proposal bundle through a hard-coded
`/tmp/claude-0/v2e-proposal-checkout` and called `pytest.skip` when it was
absent. On this machine the path happened to exist, so the tests ran and looked
like evidence. Anywhere else — CI, a fresh clone, another operator — they
**skipped silently**, and a skipped load-bearing test proves nothing precisely
where proof matters most. That is the same shape as the findings it was meant to
close: an assertion that cannot fail.

Fixed forward: a session fixture materialises the bundle from the pinned proposal
commit in this repository's own history (`git clone --shared` + detached
checkout). Verified in a fresh clone with no `/tmp` checkout present: 41 passed,
0 skipped.

---

## Finding F-1 — the M3F growable fixtures were stale, and one guard is unreachable

**Class:** C (fixture staleness, fixed) plus one open Class C disposition request.

### Fixture staleness, not a production regression

`test_growth_with_the_anchor_uses_floors` and
`test_shrunken_cohort_is_refused_even_with_the_anchor` both failed at `47c9d65`.
Neither failure was a production regression. Both fixtures manufactured "growth
evidence" by appending a fake proposal record to the registry, and the newer
production rule — every production proposal is covered by exactly one acceptance
— correctly refused that tree before either test reached the guard it meant to
exercise.

The rule is right and was not weakened. A fake proposal can never lawfully be
accepted: it has no commits, so no file-set binding and no genealogy exist for
it. Real accepted growth is what the repository already contains, so the fixture
is now a clone of the repository itself (with `.git`, so the genealogy and
file-set checks run rather than being skipped), and the mutations are applied on
top of a control that is proven to pass unmutated.

Both tests now assert the guard that is actually operative, measured rather than
assumed:

| test | expected before | operative refusal (measured) |
| --- | --- | --- |
| shrunken cohort | `shrank` (cohort floor) | `accepted_base.json does not equal the acceptance chain-head state` |
| unaccepted proposal (new) | `does not equal the accepted count` | `proposal_registry.jsonl does not equal the acceptance chain-head state` |

In both cases the acceptance chain-head pin is strictly stronger and strictly
earlier than the guard the old tests named.

### Open: the cohort floor is unreachable (Class C, for Auditor B disposition)

`src/eth_research/m3f/honest_state.py` raises
`"live cohort shrank below the accepted row count"` when the live cohort falls
below the committed record. Three separate attempts failed to reach it:

* shrinking `accepted_base.json` → caught by the acceptance chain-head pin;
* raising the committed `m3d_cohort_row_count` → caught by the
  `HONEST_STATE.md` must-reproduce-from-JSON check;
* the small-file-list fixture → caught by the proposal/acceptance count rule.

Deleting the floor entirely and re-running the M3F growable, honest-state and
audit suites: **all pass**. No input reaches it.

It is therefore defense-in-depth that nothing can currently exercise. It is NOT
being marked closed on primary-agent judgement, and no contrived test was written
to give it the appearance of coverage. Auditor B is asked to disposition it:
either it is genuinely dead code and should be removed, or a reachable regime
exists that these attempts missed and should be added as a probe. Recorded as
open until then.

## §4 — the probe truth table, and the two defects it found

`docs/V2E_ACCEPTANCE_PROBE_TRUTH_TABLE.md` (and its `.json` sibling) record 48
rows measured against `ecfa8e7`: 5 mandatory controls and 43 coordinated
attacks, each run against four readers. The harness that produces it is
committed at `tools/acceptance_probes/`, so the numbers can be re-derived rather
than taken on trust.

### The earlier 41-probe count is not cited

Auditor B's original 41-probe matrix was never persisted as machine-readable
evidence. Nothing in the new table cites it, every row was re-measured, and the
new table supersedes any earlier count. Repeating a number whose evidence no
longer exists would be exactly the kind of claim this section is meant to
eliminate.

### Two harness faults that had produced false "caught" verdicts

Both were found and fixed *before* any number here was trusted, and both are
worth recording because they are the failure mode this discipline exists to
catch — a probe that looks caught but measures nothing:

1. **The reseal rebuilt the registry unconditionally.** All five `CHAIN-*`
   mutations were silently undone by the very reseal meant to help the attacker,
   so the chain probes reported "accepted by all readers" against an unmutated
   chain. Self-hash and registry rebuild are now explicit, per-probe reseal
   steps; the CHAIN probes request neither.
2. **The recovery capsule was not rebuilt after a source edit.** Two readers
   were "catching" attacks with `recovery drill record drifted from a fresh
   drill` — capsule staleness, not a semantic refusal. The capsule, notice and
   drill are now rebuilt as part of the governance reseal. This is the same P-2
   mistake recorded earlier in this log, caught a second time by applying the
   same rule.

### D-1 (Class C, FIXED): the file-set binding did not have to be about the record

`verify_record_binding` re-derives the file set from **its own**
`proposal_parent_commit` / `proposal_commit`. Nothing checked those were the
record's pins. Repointing `proposal_head_commit` at any other commit that also
carries the same proposal manifest therefore passed every production check: the
binding still re-derived from the untouched original commits, and A06's "this
commit carries the proposal" test still succeeded.

Both shadow readers refused it (`binding certifies a different commit than the
record's proposal_head_commit`); the production path accepted it. Measured as
probe `GIT-01`. A08 now cross-checks both commit fields first; `GIT-01` refuses
on all four readers, the control still passes, and deletion mutant `D-BIND`
confirms the new check is what catches it. Catalogued as `BIND-01`.

### D-2 (Class C, FIXED): the invariant catalog overstated two coverage claims

The catalog claimed `ROOT-03` and `PROV-04` on all three enforcement paths. The
probes contradict both:

* `ROOT-02` (rewrite both working-tree authority tables plus the registry
  genesis root, then reseal everything) is refused by production alone. The
  shadow paths derive the root from history and never read the working-tree
  copies — safe, but it means neither *notices* a rewritten cache. `ROOT-03` is
  production-only.
* `PROV-04` (a second production proposal no acceptance covers) is refused by
  production alone. Neither shadow path enumerates the proposals directory.

Both now carry their measured gap. `tests/test_m3e_invariant_catalog.py` reads
the committed truth table and fails when any path accepted an attack aimed at an
invariant that path claims to enforce, naming the probe that disproves it. The
check was mutation-tested: claiming `DATA-03` on all three paths fails with the
four probes that refute it.

### Recorded, not fixed: `GIT-07` reaches a different guard than intended

A `refs/replace` entry substituting the pinned commit is refused by all four
readers, but not by `GEN-04`, the check written for that attack: A06's ancestry
test resolves the replaced object and fails first, so `GEN-04` never runs. That
is a defence-ordering observation rather than a hole — the attack is refused
everywhere, and `GEN-04` is probed directly in
`tests/test_m3e_commit_genealogy.py`. It is recorded as
`REFUSED_BY_ANOTHER_GUARD` rather than counted as a catch.

## G-1 (Class B, OPEN — architectural, needs a governance decision)

### The GA release baseline and the V2D growable cohort contradict each other

Four full-suite failures on this branch share one root cause, and it is not test
staleness:

* `test_ga_release_artifacts::test_release_evidence_is_current`
* `test_ga_release_artifacts::test_ga_hardening_changed_no_governed_artifact`
* `test_private_release::test_check_passes_and_mutates_nothing`
* `test_private_release::test_committed_manifest_source_fields_reproduce`

`tools/release_evidence.governed_baseline_digest()` hashes **every file under
`research/` except** `research/v2a/`, `research/v2b/`, `research/v2/` and
`research/v2ab/`. That digest is pinned into the frozen v1.1.0 release evidence
(`required_governed_state_digest` in the private distribution policy, and
`governed_state_digest` in the release and private-release manifests), and the
tests assert it still reproduces from the tree.

The exclusion list encodes an assumption that was true when it was written: after
GA, only V2A/V2B research would move, so everything else under `research/` could
be treated as frozen released evidence.

V2D falsified that assumption. It activated a **growable** prospective cohort
whose entire purpose is to append to `research/m3d/` and `research/m3e/` on a
schedule, under governed acceptance. This branch is simply the first time that
growth has actually landed, so it is the first time the contradiction is visible.

**This is not a stale fixture and must not be fixed by relaxing an assertion.**
The digest is doing exactly what it was built to do; the surface it was pointed at
stopped being frozen.

Two candidate resolutions, with the trade-off stated honestly:

1. **Narrow the baseline to what is actually frozen.** Add the specific growable
   prospective paths to `_POST_BASELINE_PREFIXES`, exactly as V2A/V2B research
   already is. This keeps the invariant's purpose — released artifacts have not
   been tampered with — while acknowledging that the cohort is designed to grow.
   The excluded surface is *not* left unguarded: the acceptance chain,
   `m3f.growable` and the stdlib verifier all bind those same paths, and the probe
   truth table measures that they do. The exclusion moves the surface to the guard
   that understands its lifecycle rather than removing a guard.
2. **Rebuild the frozen release evidence to the new digest.** Rejected. The v1.1.0
   release evidence would then change every time a scheduled cohort update lands,
   which does not weaken the invariant so much as delete it.

Resolution 1 is the primary agent's recommendation, but it changes the meaning of
a released artifact's provenance claim, so it is recorded here as OPEN pending
independent review rather than applied unilaterally. Whichever is chosen, the
exclusion must be narrow — the specific growable paths, not all of
`research/m3d/` — and a test must assert that every excluded path is covered by
the acceptance-layer guards instead.

Recorded during V2F §1 preflight; the failures were found by running the full
suite from an immutable worktree rather than the targeted subsets prior
checkpoints on this branch had relied on.
