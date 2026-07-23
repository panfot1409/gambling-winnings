# V2C Post-Qualification Red Team

Five independent adversarial auditors examined the committed offline operational qualification (OQ)
run at `530f182` (and the follow-on hardening/doc commits) on the branch
`claude/v2c-prospective-operations-qualification`. Each was read-only, was given a distinct mandate,
and was tasked with *breaking* a specific claim. This is the record of their findings and the
disposition of each.

**Outcome:** the committed run survives adversarial scrutiny. It is a genuine, byte-deterministic
execution whose terminal digests re-derive from the frozen source; it is independently accepted by
the OQ-Q oracle and the deep archive verifier; it evaluates **no** strategy or candidate; and all
three sealed partitions stay byte-empty. One actionable gap (no from-source re-derivation of the
committed digest) was surfaced by two auditors independently and has been **fixed**. All other
findings are Low / by-design / document-only. Full suite green on CPython 3.12 (exit 0) and 3.13
(3632 passed, 62 skipped, 0 failed).

## Auditors and verdicts

| Auditor | Mandate | Verdict |
|---------|---------|---------|
| A | Run integrity & determinism | Determinism/reproducibility/digest-integrity **sound**; 1 by-design provenance gap (fixed), 1 Low |
| B | Test-isolation soundness | **Claim upheld**; isolation faithful, coverage added not reduced; 2 Low/by-design (one fixed) |
| C | Sealed-partition & no-evaluation invariant | **Claim holds**; no strategy evaluated, sealed ledgers byte-empty; 1 Low document-only |
| D | Freeze / activation / supersession consistency | **All clean**; frozen surface untouched, freeze reproduces, e4b3cc3 superseded, 2a9e528 untouched |
| E | CI/replay dual-state & governance drift | **Clean**; CI green both legs, v2c-replay re-verifies State B, zero config/source drift |

## Key confirmations (what the auditors proved)

- **Byte-determinism (A):** two independent re-executions of the frozen source produced
  byte-identical `result` / `report` / `manifest` / `bundle`, all reproducing the committed digests.
  No wall-clock, RNG, dict-order, or filesystem-order leakage reaches the result.
- **No strategy evaluated (C):** the runner takes no candidate parameter and hard-wires
  `target_weight = 0.0`; a live re-run reproduced the exact committed operational counts with
  exactly-zero exposure/turnover/fills. The firewall admits only `cash_control_operation`; no real
  market data is read.
- **Sealed partitions untouched (C):** all three ledgers are committed as 0-byte blobs.
- **Frozen surface untouched (D):** the run commit changed only the registry, the published archive,
  and test files — no frozen source, no `docs/V2C_PLAN.md`, no governance invariant. The OQ-E2 freeze
  reproduces, the OQ-E2A anchor binds `cea86a5`, `e4b3cc3` stays superseded, `2a9e528` is unchanged.
- **Isolation faithful (B):** the 11 identity-bound / frozen artifacts the orchestrator reads from
  `repo_root` are byte-identical between the real tree and the `pristine_oq_repo` copy; the fixture
  rewinds only the three run-produced surfaces, each independently certified on the real tree.
- **CI dual-state (E):** the `v2c-replay` workflow (read-only, SHA-pinned, fail-closed) runs the
  state-aware `replay` which — with the registry `completed` — performs the 16-check deep verify +
  OQ-Q oracle acceptance (State B), plus the full V2C suite. Green on both 3.12 and 3.13.

## The one fix applied

**A-1 / B-item-4 — the committed digest did not re-derive from the frozen source.**
Both auditors observed that the shipped offline verifier proves the archive is internally consistent,
independently accepted, and hash-immutable — but nothing re-executed the frozen source to prove the
committed result is what that source *actually produces*, and the certification test pinned the
terminal digests only as string literals (a self-referential read-back). A self-consistent
fabrication of `oq_result.json` (with every dependent digest and the registry chain recomputed) would
satisfy replay/verify/oracle.

**Fix (`a7dee93`, test layer — the OQ source is frozen and unmodifiable):**
`tests/test_v2c_oq_committed_run.py::test_committed_digests_re_derive_from_the_frozen_source`
registers → starts → executes → assembles the archive from an isolated copy of the frozen source at
the canonical slot count (3800) and asserts the re-derived `result_sha256` / `result_bundle_sha256`
equal the committed literals. A forged result cannot pass both this and the read-back assertions
unless the frozen source itself were altered — which `verify_oq_source_freeze` independently refuses.
This turns the digest lock from a tautology into a from-source provenance proof, closing the gap on
the authoritative CPython 3.12 leg. Verified: 3.12 → 9 passed; 3.13 → 8 passed, 1 skipped.

## Document-only / by-design findings

See `docs/V2C_FINDINGS.md` for the full register. In brief:

- **A-2 (Low, by-design):** the pristine-branch `replay`/`verify` CLIs do not flag an orphaned
  archive when the registry is truncated. No `qualified` certification is emitted and the one-shot
  budget cannot actually be reset (the `no_prior_run_artifacts` gate blocks re-register). Frozen CLI.
- **B-Low:** the `pristine_oq_repo` fixture re-declares the run-produced relpaths as literals rather
  than importing the source constants; bounded by the frozen source and **fails safe** (a stale
  literal makes a leftover artifact trip the gate, so the test fails loudly, never passes falsely).
- **C-Low (document-only):** the secondary narration vocabulary regex in the frozen `result.py` /
  `oracle.py` does not strip zero-width / Unicode-confusable characters. Non-exploitable — the
  templates are code-controlled with no candidate/user text, and the authoritative no-strategy gates
  (firewall + numeric zero-exposure) do not depend on it. Frozen; cannot be modified post-freeze.
- **D-observation (by-design):** the OQ-E2A activation anchor's 40-hex commit value is
  self-consistent-by-construction, not cryptographically attested (no signing key); the code and the
  anchor statement disclose this explicitly, and D verified the recorded commit is factually the
  freeze commit via git history.
- **E-0 (informational):** the branch HEAD advanced (`530f182` → `6f7760e`) during the audit as the
  hardening + doc commits landed; E confirmed those commits are additive and clean.

## Threat-model boundary (unchanged, documented)

A fully self-consistent forgery by an actor who rewrites **both** the committed tree **and** the
frozen source (and the test literals) is out of scope for the offline verifier; detection is
delegated to human review of signed git history. There is no signing key in this environment. This
boundary is stated in the freeze statement and in `docs/V2C_SECURITY.md`.
