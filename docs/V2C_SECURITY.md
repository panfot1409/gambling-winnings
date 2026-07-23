# V2C OQ — Security Posture

This document states the threat model of the V2C offline operational qualification, the controls
that enforce it, and — honestly — the boundaries those controls do not cross. It reflects the
post-qualification red team (see `docs/V2C_POSTQUAL_RED_TEAM.md` and `docs/V2C_FINDINGS.md`).

## 1. Threat model

**Trusted:** the repository maintainer who can write the branch, and git history as the ultimate
provenance anchor. There is **no signing key** in this environment, so the design does not claim
cryptographic attestation of provenance.

**Defended against:**

- Accidental corruption or drift of the frozen source, governance artifacts, or published archive.
- A self-consistent tamper of the *result* that recomputes every dependent digest and the registry
  chain but does **not** alter the frozen source.
- Any attempt to evaluate a strategy/candidate, read real market data, or contaminate a sealed
  partition through the qualification path.
- An orphaned prior run being laundered into a fresh one-shot budget.

**Explicitly out of scope:** a fully self-consistent forgery by an actor who rewrites *both* the
committed tree *and* the frozen source and edits the test literals. Detection of that case is
delegated to human review of signed git history — a documented, deliberate boundary.

## 2. Controls

### 2.1 Candidate-free execution firewall (fail-closed)
`guard_request_kind` admits only the `cash_control_operation` request kind; `resolve_operational_target`
is a strict exact-match allowlist that resolves only the candidate-free `cash_control` target. Real
candidate ids, instrument symbols, market-data kinds, callables, modules, and case/whitespace/
zero-width variants are all refused. The module imports no candidate or engine code. The firewall's
scan normalizes inputs (strips zero-width characters) before matching. This is the **authoritative**
"no strategy evaluated" control, and it is independent of any text scan.

### 2.2 Numeric zero-exposure invariant
The runner hard-wires `target_weight = 0.0` on every step; the committed result carries exactly-zero
requested/approved exposure, turnover, and fills, and holds 0 book units (final cash = starting
cash). The OQ-Q oracle and the deep verifier independently re-derive this from the run's own
measurements — a second authoritative gate, also independent of any text scan.

### 2.3 Sealed partitions
The three sealed ledgers (`research/m2b/test_evaluations.jsonl`,
`research/m3a/development_gate_access.jsonl`, `research/m3d/prospective_evaluations.jsonl`) are
committed as **0-byte blobs** and asserted byte-empty by the orchestrator gate, the replay CLI (twice),
and the committed-run certification. The qualification touches no sealed partition.

### 2.4 Integrity chain (keyless) + from-source re-derivation
- The registry is an append-only, hash-linked chain (`entry_hash = canonical_sha256(body)`, each
  event chaining onto the prior `entry_hash`); a naive edit that does not recompute the chain is
  caught.
- Published artifacts are write-once; per-run paths are never overwritten.
- The committed terminal digests **re-derive from the frozen source** at the canonical slot count
  (`tests/test_v2c_oq_committed_run.py::test_committed_digests_re_derive_from_the_frozen_source`),
  so a self-consistent result forgery that leaves the frozen source intact is caught in CI.
- Altering the frozen source is independently refused by `verify_oq_source_freeze`.

### 2.5 Freeze / activation / supersession
The OQ-E2 source freeze reproduces; the OQ-E2A activation anchor re-derives from it and binds the
freeze commit `cea86a5`; the premature OQ-E freeze `e4b3cc3` is recorded superseded and can never
authorize a run.

### 2.6 Workflow security
The `v2c-replay` CI workflow is read-only (`contents: read`), SHA-pinned, and runs only the
read-only status/replay/verify CLIs plus the test suite; it mutates nothing. The
`inactive_workflow_templates/*.yml.inactive` probe templates are inert (wrong extension) and can
never be dispatched. No acquisition or network-egress workflow is active.

### 2.7 Distribution
The repository is **private**; version is `2.0.0.dev2` (a development pre-release, never published to
an index). `sell_ready` is derived-**false**.

## 3. Documented limitations (accepted)

- **Keyless provenance.** Without a signing key, genuineness ultimately rests on git history +
  write-once publication + from-source re-derivation, not on a signature. (Red-team Finding: A-1,
  by-design.)
- **Secondary narration vocabulary screen.** The result/report forbidden-term regex (in the frozen
  `result.py` / `oracle.py`) does not strip zero-width / Unicode-confusable characters, unlike the
  firewall's normalizer. It is non-exploitable: the templates are code-controlled with no candidate/
  user text flowing in, and the authoritative no-strategy gates (2.1, 2.2) do not depend on it. The
  modules are frozen and cannot be modified post-freeze. (Red-team Finding: C-LOW, document-only.)
- **Read-only CLI state asymmetry.** A truncated registry with a surviving archive is not flagged by
  the pristine-branch replay/verify CLIs, but no `qualified` certification is emitted and the
  one-shot budget cannot actually be reset (2.4 / the `no_prior_run_artifacts` gate). (Red-team
  Finding: A-2, low, by-design.)
