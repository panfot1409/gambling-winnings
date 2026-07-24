# V2E Stack Acceptance Audit — PR #23 merge and PR #22 forward-only proposal acceptance

Scope: V2F §2 (close the V2E stack). Two independent acceptances are recorded here:
§2.1 the V2E private operations dashboard + disabled paper harness (PR #23), and
§2.2 the DATA-ONLY prospective-cohort update proposal (PR #22).

Neither acceptance evaluates a strategy, authorizes an evaluation, starts paper
trading, or moves money. All three sealed partitions remain byte-empty
(`e3b0c442…`). V2 remains **not sell-ready**.

---

## Part 1 — §2.1: PR #23 (V2E dashboard + disabled paper harness)

### 1.1 Pre-merge state

| Fact | Value |
|---|---|
| Base (main) | `ba2dcc1d63f29a009d3660be2d960388a9615da0` |
| Head | `ce88d83637022a25fbdb189715c032abb02a0ffc` |
| Diff | 17 files, +2509 / −6 |
| Checks | all terminal green on the exact head |
| Draft | yes (held for review) |

### 1.2 Independent acceptance auditors (three, read-only)

All three returned **ACCEPT** with zero Class A/B/C findings:

1. **dashboard/web-security** — verified GET/HEAD-only fixed routes; every other
   method refused 405; loopback default with LAN binding requiring explicit opt-in
   plus a visible warning; empty/wildcard/IPv6-wildcard/encoded-host and
   forwarded-header inputs cannot bypass the loopback restriction; CSP and
   defensive headers present on both success and refusal paths; HTML escaped
   exactly once; no traceback, credential, token, header value, or source/strategy
   logic reachable; no mutation or control endpoint exists.
2. **governance/data-firewall** — verified the patch computes no strategy signal
   and no market return; cannot read sealed values; checks the sealed ledgers
   **before** all other state; cannot conflate accepted with proposed cohort state;
   fails closed on malformed JSON, duplicate keys, NaN/Infinity, bool-as-int,
   unknown/missing keys, symlinks, traversal, and oversized inputs; the pending
   proposal is manifest-authoritative and a stale/wrong-parent proposal fails
   closed.
3. **paper-lifecycle/state-machine** — verified the lifecycle cannot leave
   `disabled` without all 17 requirements; requirement values are type-pinned
   booleans and cannot be hostile objects; the activation token cannot be
   constructed, forged, subclassed, or replayed against degraded requirements; no
   flag or environment variable is a bypass; the resting derivation can never
   yield `active`; the zero-exposure rehearsal is calculation-free with respect to
   strategy/backtest execution.

**Class D deferrals** (inert, non-blocking, carried into the V2F bug log for
hardening; none affects the read-only or fail-closed guarantees): stdlib
protocol-error pages (400/414/431/501) lack the custom security-header set;
`_qualification_present` does not walk ancestor directories for symlinks; the
proposal manifest file itself is not regular-file-checked before reading;
`row_count` coercion via `int(str(...))`; `canonical_content_match` sits outside
the manifest's self-hashed block; minor test gaps.

### 1.3 Disposable-clone true-merge simulation (exact)

| Property | Result |
|---|---|
| Parents | `ba2dcc1` + `ce88d83` (two — a true merge, never squash/rebase) |
| `tree(merge)` | `bdcc749b62029e5ea1dd355ecd77301b7722dc19` |
| `tree(branch)` | `bdcc749b62029e5ea1dd355ecd77301b7722dc19` (identical) |
| `research/` drift vs base | **empty** |
| Governance drift | exactly 2 intended files (`fable5_source_freeze.json`, `fable5_system_inventory.json`) |
| Fast battery | 83 tests, exit 0 |
| fable5 freeze verify | OK |
| M3E deep replay | OK |

### 1.4 Merge executed

Body updated honestly (auditor record + Class D deferrals), undrafted **solely**
as the merge prerequisite, merged as a **true merge commit**, head branch
**retained** (not deleted).

| Property | Value |
|---|---|
| Merge commit | `f42e5b5c8886128878e5e9daa45f10566c7426eb` |
| Parents | `ba2dcc1d63f2…` + `ce88d8363702…` |
| `tree(main)` | `bdcc749b62029e5ea1dd355ecd77301b7722dc19` — identical to the simulation |
| Ancestry | both parents are ancestors of main |
| Sealed ledgers after | all three `e3b0c442…` (byte-empty) |
| Post-merge CI | **all 12 workflows completed green** on `f42e5b5` (CI, M2B/M3A/M3B/M3C/M3D/M3E/M3F/M4B/V2B/V2C Replay, V2 Fable 5 Replay) |

§2.1 is therefore **complete**: checks terminal green, audits clean, simulation
exact, true merge with both parents, branch retained, post-merge CI fully green,
local main synchronized.

---

## Part 2 — §2.2: PR #22 (prospective-cohort update proposal)

### 2.1 The object accepted

| Fact | Value |
|---|---|
| Bot head | `779df6bb6c7ab4ac312e9d8fe7028392581db237` (1 commit, 19 files) |
| Proposal id | `20260715-20260724-315846f9ec5196b4` |
| Source commit | `ba2dcc1` (workflow run `30068014058`) |
| Window | 2026-07-15 → 2026-07-23, 9 settled completed days |
| Cohort | 3 → **12** of 365 rows (still immature) |
| Two-runner agreement | byte-identical payloads, `canonical_content_match: true` |
| Governance flags | all false; `evaluation_authorized` stays false |
| Files touched | only `research/m3d/` and `research/m3e/` — no code, no workflows, no governance |

### 2.2 Reproduction of the five merge-preview failures (done before any fix)

Reproduced in a disposable clone at the exact two-parent merge preview of
`f42e5b5c` ⟕ `779df6bb`. **The engines were never the problem** — every deep
replay passed; what failed were pins of the *pre-proposal accepted state*:

| Red check | Engine result | What actually failed | Stale pin |
|---|---|---|---|
| M3D Replay | `m3d.replay --deep` **passes** | `test_cohort_is_immature_and_never_authorized` | literal `remaining_rows == 362` (365 − 3) |
| M3E Replay | `m3e.replay --deep` **passes** | 7 × `test_m3e_proposal.py`, `test_registry_is_deterministic_and_matches_committed` | tests model the committed proposal as *pending against the current base*; `build_registry_bytes()` could not derive a production-proposal record |
| M3F Replay | catalog byte-lattice OK | `02_governance_state_legal` ("inactive M3E but a production proposal exists"), `08_semantic_oracles`/`oracle --check` (`m3e_registry_chain`), `09_recovery_capsule`, `10_recovery_drill`, 10 test files, the stdlib verifier | M3F froze "ready-not-active": *zero* production proposals was a legality invariant, and the capsule pinned the six cohort files byte-exact |
| V2AB Stack | — | `v2ab.acceptance --check --deep`, `test_v2ab_acceptance.py` | 13 "unlisted governed artifact" + 6 "bytes changed": the stack freeze table enumerated the governed tree with no growth awareness |
| CI | ruff/mypy unaffected (data-only diff) | union of the above + V2E dashboard tests pinned to 3-row/pending state | same root cause |

**Root cause, stated once:** every red surface pinned the pre-proposal accepted
state. That is *correct fail-closed behavior for an unaccepted proposal* — the
missing piece was a governed, explicit, append-only **acceptance event** the
verifiers could consume forward-only.

### 2.3 Path decision

The required layer is **not minimal** (new schema, chained registry, legality
migration across M3F/V2AB, an independent stdlib reimplementation, registry-rebuild
derivation, and a mutation matrix), so per the directive the **dedicated-branch**
path was taken:

1. PR #22 and its bot branch are preserved untouched as immutable proposal evidence.
2. `claude/v2e-proposal-acceptance-001` was created from post-V2E main `f42e5b5c`.
3. The exact bot head `779df6bb` was merged into it with a **true merge commit**
   (`fe65cdd`), importing the 19 files verbatim — the merge changes no bytes.
4. Acceptance machinery was layered on top in append-only commits.

### 2.4 The acceptance layer (forward-only)

- `research/m3e/acceptance_registry.jsonl` — append-only, hash-chained. Its
  **genesis pins the exact pre-acceptance sha256 of all six transitioned cohort
  paths**, cross-checked against two independently byte-frozen authority tables
  (`docs/M3C_M3E_STACK_FREEZE_TABLE.json`, `research/v2ab/stack_freeze_table.json`);
  any disagreement is a hard stop, so a forged genesis cannot re-root the chain.
  (The M3F freeze catalog is deliberately *not* an authority — it is rebuilt at
  re-registration and snapshots current, not pre-acceptance, state.)
- `research/m3e/acceptances/20260715-20260724-315846f9ec5196b4/acceptance.json` —
  self-hashed (domain-separated) record binding every item the directive requires:
  proposal id; proposal head `779df6bb…`; expected parent `ba2dcc1`; both runners'
  plan/receipt/raw-response hashes and identities; canonical content fingerprint;
  previous accepted manifest (sha, fingerprint `bb6dd392…`, 3 rows); new accepted
  manifest (sha, fingerprint `ab22a086…`, 12 rows, plus the exact sha256 of all six
  transitioned files and all 13 created evidence files); exact append interval
  (2026-07-15 → 2026-07-23, 9 rows); append-only proof (0 prior rows changed, 0
  deleted, recomputed — not asserted); quality result; all governance flags false;
  all three sealed-ledger paths with the empty-file digest; acceptance time.
  It is derivable **only** after the full 11-check `verify_landed_update` graph passes.
- `acceptance_completion.json` — the two-phase commit binding: a record cannot
  contain its own publication commit, so the completion record binds it
  (`1705057a…`), mirroring the established M3A/M3B completion-intent pattern.
- Publication is transactional (temp file + fsync + atomic rename) with a strict
  read-back re-verification of the whole chain.

**Invariants held (all tested):** the cohort verifier was never weakened; there is
no "anything newer is fine" rule — production expectation is always the single
exact state `genesis pins ⊕ ordered chain`; no receipt, raw response, proposal file,
or bot commit was edited; a production proposal **without** a covering acceptance
record remains illegal (exactly the condition that made the five checks red); and
deleting, reordering, duplicating, or editing any chain element breaks a hash chain
or a self-hash and fails closed.

### 2.5 Verifier migrations (historical mode preserved throughout)

- **`eth_research.m3e.acceptance`** (new) — writer + canonical verifier
  (`verify_acceptance_program`: chain, coverage both ways, tree-equals-chain-head,
  created-evidence pins, deep landed re-proof, ancestry of the bound commits,
  sealed ledgers).
- **`eth_research.m3f.growable`** — gains `read_acceptance_state`, an
  **import-isolated strict re-implementation** of the chain walk (M3F never imports
  the layer it audits). Consumed by the honest-state derivation, the governance
  state machine (new exact `reviewed_growth_active` posture; an uncovered proposal
  is still impossible), the `m3e_registry_chain` oracle, catalog check 15, the
  recovery capsule, and a new `dropped_acceptance_record` failure drill. The capsule
  now carries the V2D anchor + authority tables so the offline drill can re-prove
  lawful growth.
- **`tools/m3f_independent_verify.py`** — a third, stdlib-only reimplementation of
  the entire chain walk (new check `09_acceptance_chain`), sharing no code with the
  package readers.
- **`eth_research.v2ab.freeze_table`** — transitioned paths verify against the
  chain-head state, created evidence against acceptance pins, and the two
  rebuildable M3F artifacts delegate to their reproduce-from-tree builders;
  everything else stays byte-anchored. The committed table's bytes never change.
- **`eth_research.m3e.registry.build_registry_bytes`** — derives production-proposal
  records deterministically from committed proposal bundles, so "deterministic and
  matches committed" remains a *full rebuild*, not a relaxation.
- **Tests** — pre-growth literals were re-derived from committed state and
  cross-checked against the acceptance chain (never tautologically from the file
  under test); every tamper/negative case still fails on tamper; no test was
  deleted, skipped, or xfailed.

### 2.6 Defects found and fixed while migrating (fail-closed hardening)

1. `verify_honest_state` raised an uncaught `KeyError` out of the Markdown renderer
   when the committed record was tampered/truncated — now a `M3FValidationError`.
   (The blanket "missing key" check was deliberately *not* used: the committed
   record is the immutable at-acceptance snapshot and may lack strictly-later
   fields; every immutable fact is still compared exactly.)
2. Two synthetic governance fixtures copied the (now grown) real registry without
   the evidence that legalizes it, so tests tripped the wrong invariant. Fixed by
   making the fixtures self-consistent, and by slicing the registry's genuine
   pre-proposal prefix rather than pasting a literal.

### 2.7 Local verification status at the time of writing

| Gate | Result |
|---|---|
| `m3e.acceptance check` | OK (A01–A07, including the deep landed re-proof) |
| `m3f.audit --deep` | OK (all checks, zero failures) |
| `m3f.replay --check`, `m3f.recovery --deep`, `m3f.oracle --check` | OK |
| `tools/m3f_independent_verify.py` | OK — 9 checks, 0 failures |
| `v2ab.acceptance --check --deep` | `{"ok": true, "problems": []}` |
| ruff check / ruff format | clean |
| mypy (strict, 637 files) | Success, no issues |
| Full pytest suite | running at the time of writing — **not yet claimed green** |
| Sealed ledgers | all three byte-empty (`e3b0c442…`) |

Remaining §2.2 work (not yet done, and therefore not claimed): finish the full
suite green, run the five independent auditors (raw-data/provenance; append-only
semantics; accepted-vs-proposed state; workflow scope; historical replay
neutrality), open the draft acceptance PR, get every check green, simulate the
true merge, merge only after exact acceptance, retain all branches, and confirm
the post-merge checklist (accepted cohort equals exactly the verified proposed
state; no row used in research; no strategy code touched it; sealed ledgers empty;
the V2E dashboard reports the cohort as accepted rather than pending;
V2A/V2B/V2C/Fable 5 historical state byte-reproducible; collection remains
data-only).
