# Milestone 3F — threat model

M3F adds an *independent verification, hermetic recovery, and supply-chain
closure* layer over the already-accepted M2B–M3E research stack. This document
states what M3F defends, whom it defends against, the controls it relies on, and —
honestly — what it does **not** protect against.

M3F is verification-only and recovery-only. It never fetches data, evaluates a
strategy, computes a return or metric, reads a sealed partition, mutates a ledger,
publishes a proposal, or consults the wall clock to decide integrity. Every claim
it makes is a deterministic function of committed bytes.

## Assets

1. **Governance truth.** Four facts that must hold forever:
   - the M3C candidate verdict is `rejected_for_development_gate_promotion`;
   - the M3D cohort is immature (row count below the maturity threshold) and
     `evaluation_authorized` is false;
   - M3E is inactive with zero production proposals;
   - no standing workflow can write repository contents.
2. **Sealed access ledgers.** Three byte-empty JSONL files
   (`research/m2b/test_evaluations.jsonl`, `research/m3a/development_gate_access.jsonl`,
   `research/m3d/prospective_evaluations.jsonl`), each with the empty-file SHA-256
   `e3b0c442…7852b855`. A single appended byte is a governance event.
3. **The frozen accepted stack.** Every tracked artifact under `research/` for
   M2B–M3E, bound by the freeze catalog to its source-freeze blob bytes.
4. **Reproducibility.** The ability to rebuild every committed M3F artifact — and,
   via the recovery capsule, the accepted research state — byte-for-byte.

## Adversary model

The adversary can propose commits, open pull requests, and edit any file (they are
a contributor whose change reaches review or CI). They **cannot** rewrite accepted
history that is already merged, and they do not control the reviewer who merges.
The goal of the controls below is that any tampering with an asset is *detected*
before it can be accepted — M3F is tamper-evident, not tamper-proof.

Threats considered:

- **T1 — Silent governance drift.** A change flips a governance fact (promotes the
  rejected candidate, authorizes evaluation, activates M3E, adds a write-capable
  workflow) while presenting as benign.
- **T2 — Sealed-partition leak.** A non-empty ledger, or partition contents smuggled
  into another artifact or the recovery capsule.
- **T3 — Fabricated proposal.** A production proposal recorded in the M3E registry,
  possibly serialized to evade a fragile textual check (the F1 defect class).
- **T4 — Artifact tampering.** Editing a frozen accepted artifact, or an M3F
  artifact, so it no longer matches its recorded hash / no longer reproduces.
- **T5 — Common-mode verifier bug.** A defect in the shared parser/logic that makes
  the package verifiers *and* their checks agree on a wrong answer.
- **T6 — Supply-chain injection.** A workflow that gains write permission, pushes,
  tags, merges, pipes an installer, uploads an artifact, or pins an action to a
  mutable ref; or a dependency with no reproducible source identity.
- **T7 — Non-reproducible artifact.** An M3F artifact whose bytes depend on wall
  clock, machine, interpreter, or iteration order, so "reproduces byte-for-byte"
  silently becomes meaningless.

## Controls

| Threat | Control |
|---|---|
| T1 | `honest_state.derive_honest_state` fails closed on the four forever-invariants; `state_machine` refuses impossible label combinations; `audit.verify_repository_freeze` runs both as always-available checks and returns early if governance is untrustworthy. |
| T2 | Empty-ledger check in honest state, catalog, oracle, independent verifier, recovery drill, and CI (before **and** after replay); `bundle.build_manifest` refuses to bundle a non-empty ledger. |
| T3 | `validation.count_created_proposals` parses each registry line (whitespace-independent) and is fail-closed: a smuggled truthy non-bool is counted. Used by both honest state and catalog. |
| T4 | `freeze_catalog` re-hashes every accepted artifact against its recorded SHA-256 with an anti-orphan enumeration; each M3F artifact reproduces from bytes through its own verifier; the mutation matrix proves every artifact is covered. |
| T5 | `tools/m3f_independent_verify.py` re-derives the governance facts and re-hashes artifacts through a **separate, standard-library-only** code path that imports neither `eth_research` nor any third-party package; a static firewall test enforces the isolation. |
| T6 | `workflow_inventory` fail-closes on write permission, plain/force push, merge/tag/release verbs, unpinned actions, piped installers, market hosts, and artifact uploads (`.yml` **and** `.yaml`); `dependency_inventory` fail-closes on duplicate identity or a package with no reproducible source. |
| T7 | Every artifact is canonical JSON (sorted keys, fixed indent, trailing newline, finite-only) with sorted file lists and no timestamps; the compat-recovery CI matrix rebuilds byte-for-byte on CPython 3.12 and 3.13; determinism tests re-run each builder and diff the bytes. |

## Trust boundaries

- **Hash binding is operational tamper-evidence, not a cryptographic signature or a
  remote attestation.** An adversary who can rewrite both an artifact and its
  recorded hash in the same accepted commit defeats hash binding; the defense is
  human review of the diff plus the independent verifier's separate recomputation.
- **The independent verifier trusts only the Python standard library and the git
  checkout.** It does not trust the `eth_research` package it shadows.
- **CI trusts only SHA-pinned actions and a hash-pinned `uv` installer.** No step
  has write permission; no step reaches a market host.

## Residual risks (explicitly not defended)

- **Coordinated hash+artifact rewrite in one accepted commit** (see above) — caught
  only by review and by the independent verifier disagreeing.
- **A compromised reviewer** who accepts a red diff. M3F makes tampering *visible*;
  it cannot force a human to look.
- **A defect in CPython, git, or the standard library** shared by both the package
  and independent verifiers. The two verifiers reduce, but cannot eliminate,
  common-mode risk below the interpreter.
- **Anything outside the committed bytes** — a compromised runner image, a
  malicious local environment — is out of scope; M3F verifies artifacts, not the
  machine that runs it.

M3F does not activate M3E, does not evaluate any strategy or gate, does not fetch
prospective data, and does not create any production proposal. It only proves, from
committed bytes, that none of those things has happened.
