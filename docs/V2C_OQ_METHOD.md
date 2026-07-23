# V2C Offline Operational Qualification — Method & Committed Run

**Status:** run executed, accepted, committed, CI-green. Version `2.0.0.dev2`. Repository private.

**Authorized verdict for this milestone:**
> V2C COMPLETE — PROSPECTIVE-EVIDENCE AND OFFLINE-OPERATIONS QUALIFICATION READY, NOT ACTIVE;
> NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.

This document is the methodology of record for the V2C offline operational qualification (OQ): what
it is, what it deliberately is **not**, the governance sequence that authorized it, the identity and
digests of the committed run, and the verification model that lets anyone re-check it.

---

## 1. What the OQ is (and is not)

The OQ is a **candidate-free operational qualification** of the V2C shadow-operations harness. It
exercises the run/recovery/SLO/resource machinery against a deterministic synthetic fixture using a
single hard-wired **cash-control** target (`target_weight = 0.0` on every step). It measures
operational properties only — accepted-step counts, journal byte/event counts, resource bounds,
crash-recovery, SLO criteria — and asserts **exactly-zero** risky exposure, turnover, and fills.

It is **not** a strategy evaluation. No candidate, return, P&L, signal, alpha, portfolio, or
market-data evaluation occurs anywhere in the run. The execution firewall admits only the
`cash_control_operation` request kind and resolves only the candidate-free `cash_control` target;
all real candidate ids, instrument symbols, market-data kinds, callables, and modules are refused
fail-closed. Prices are a deterministic synthetic triangular wave; there is no network, no file
read of market data, and no wall-clock or RNG input to the result.

Consequently the OQ says nothing about whether any strategy is profitable or sell-ready. `sell_ready`
remains derived-**false**. The OQ certifies that the *offline operations platform* runs correctly and
deterministically — one prerequisite among many — not that a product exists.

## 2. Governance sequence

The run was authorized by a strict, append-only governance sequence, each step a separate commit:

| Step  | Commit    | Artifact / event                                                            |
|-------|-----------|-----------------------------------------------------------------------------|
| OQ-E2 | `cea86a5` | Replacement source freeze (`governance/v2c/oq_source_freeze.json`, schema 2) |
| OQ-E2A| `f30e284` | Activation anchor (`governance/v2c/oq_e2_activation.json`) binding `cea86a5` |
| (CI)  | `f4a7097` | Guard the live-lifecycle OQ tests to CPython 3.12 on the compatibility leg   |
| OQ-R/P/Q | `530f182` | Register → execute → accept + commit the immutable run archive           |

The premature OQ-E freeze (`e4b3cc3`) is recorded **superseded** in the append-only supersession
ledger and can never authorize a registration or execution. The OQ-E2A anchor re-derives from the
live OQ-E2 freeze it names; the one fact only git history can settle — that `cea86a5` genuinely
carries the freeze — is recorded honestly, not cryptographically attested (there is no signing key).

## 3. The committed run

- **Registry** (`governance/v2c/oq_registry.jsonl`): a hash-linked chain `registered → started →
  completed`, verdict `qualified`.
- **Archive** (`governance/v2c/qualifications/v2c_offline_operational_qualification_run_001/`): three
  immutable, write-once artifacts — `oq_result.json`, `oq_report.md`, `oq_archive_manifest.json`.
- **Slots executed:** 3800 (accepted 3757 per instrument; btc_usd + eth_usd).
- **Terminal digests (governance anchors — immutable):**
  - `result_sha256 = 739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897`
  - `result_bundle_sha256 = e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525`
- **Sealed partitions** (`research/m2b/test_evaluations.jsonl`,
  `research/m3a/development_gate_access.jsonl`, `research/m3d/prospective_evaluations.jsonl`):
  committed as **0-byte blobs** — the qualification touched no sealed ledger.

## 4. Verification model — how to re-check the run

Three independent, read-only checks re-verify the committed run in place (no re-execution required),
plus one from-source re-execution proof:

1. **`eth_research.v2c.oq.cli replay --repo-root .`** → the ordered 16-check certificate for a
   completed run: source-freeze + activation-anchor + protocol-bundle reproduce, premature freeze
   superseded, sealed ledgers byte-empty, the full `verify_oq_run_archive` deep check set, and
   independent OQ-Q oracle acceptance.
2. **`eth_research.v2c.oq.cli verify --repo-root .`** → the 10-check deep archive verifier:
   terminal hashes match the published bytes, the result re-scans clean with zero exposure, the
   result bundle re-derives, the report re-renders byte-for-byte, the manifest re-derives and binds.
3. **OQ-Q oracle** (`assert_independent_acceptance`) → re-derives the `qualified` verdict from the
   result's own operational measurements, independent of the runner.
4. **From-source re-execution** (`tests/test_v2c_oq_committed_run.py`,
   `test_committed_digests_re_derive_from_the_frozen_source`, CPython 3.12): registers → starts →
   executes → assembles the archive from an isolated copy of the frozen source at the canonical slot
   count and asserts the re-derived digests equal the committed literals. This binds the committed
   result to what the frozen source *actually produces* — a self-consistent fabrication of the result
   cannot pass it, because the frozen source deterministically yields `739cec5d…` (and altering the
   frozen source is independently refused by `verify_oq_source_freeze`).

The `v2c-replay` CI workflow (read-only, `contents: read`, SHA-pinned) and the full-suite `checks`
matrix run these on both the authoritative CPython 3.12 leg and the compatibility 3.13 leg; the
live-lifecycle re-execution runs only on 3.12 (the OQ runtime), while the read-only certification
re-verifies the run identically on both.

## 5. Scope of the offline verifier (honest limitation)

The shipped offline verifier proves **internal consistency + source non-drift + from-source
reproducibility** (via the CI re-execution test). It is **keyless** — there is no signing key, so
integrity rests on: (a) the append-only, hash-linked registry; (b) write-once published artifacts;
(c) the frozen-source re-derivation of the digests; and (d) git history as the provenance anchor.
An actor who can already rewrite the committed tree **and** the frozen source could fabricate a run —
but altering the frozen source is refused by `verify_oq_source_freeze`, and altering only the result
is caught by the from-source re-execution test. Detection of a fully self-consistent forgery that
also rewrote the frozen source is delegated to human review of signed git history, as disclosed in
the freeze statement. This is a deliberate, documented boundary, not a defect.

## 6. Test isolation note

Committing the completed run made the canonical tree non-pristine. Because the OQ source is frozen
(unmodifiable post-freeze), the pristine-lifecycle tests were re-pointed at a session-scoped
`pristine_oq_repo` fixture — a byte-faithful copy of the frozen source + governance + docs + runtime
contract with the registry emptied, the sealed ledgers byte-empty, and the published archive removed
— reconstructing the pre-run tree in isolation. Every surface the fixture rewinds (registry, sealed
ledgers, archive) is independently certified against the real committed tree elsewhere, so coverage
is strictly added, never reduced.
