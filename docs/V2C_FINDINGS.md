# V2C Findings Register

Formal register of findings from the V2C post-qualification red team (see
`docs/V2C_POSTQUAL_RED_TEAM.md`) against the committed offline operational qualification run. Each
finding has an id, the auditor that raised it, a severity, a status, and its disposition with
evidence. No Critical/High/Medium defect survived verification.

| id  | auditor | severity | status | one-line |
|-----|---------|----------|--------|----------|
| F-1 | A       | High-vs-claim | **fixed** (`a7dee93`) | committed digest did not re-derive from the frozen source |
| F-2 | A       | Low | by-design (frozen CLI) | pristine-branch replay/verify don't flag an orphaned archive |
| F-3 | B       | Low | by-design (fail-safe) | fixture re-declares run-produced relpaths as literals |
| F-4 | B       | Low | **fixed** (`a7dee93`) | digest lock was a read-back, not a from-source proof (same root as F-1) |
| F-5 | C       | Low | document-only (frozen) | narration vocab regex misses zero-width / Unicode-confusable |
| F-6 | A/C/D   | Info | by-design (disclosed) | integrity is keyless; provenance anchored by git + write-once + re-derivation |
| F-7 | E       | Info | no action | branch HEAD advanced during the audit (additive, clean commits) |

---

## F-1 / F-4 — committed digest did not re-derive from the frozen source — FIXED

**Raised by:** Auditor A (Finding 1, High against the literal "cannot be forged" claim; dispositioned
by-design) and Auditor B (item 4, Low) — independently.

**Description.** The shipped offline verifier (`verify_oq_run_archive`, the `replay`/`verify` CLIs,
the OQ-Q oracle) proves the published archive is internally consistent, independently accepted, and
hash-immutable — but never re-executes the frozen source, so it cannot distinguish a genuine run from
a self-consistent fabrication of `oq_result.json` (with every dependent digest and the registry chain
recomputed). The certification test pinned the terminal digests only as string literals — a
self-referential read-back, not a from-source proof. The committed run used `slots = 3800`; the
re-running lifecycle fixtures use `slots = 3650`, so none re-derived the committed `739cec5d…`.

**Evidence.** Auditor A demonstrated a working PoC: setting `accepted_count = 3999` (structurally
impossible for the frozen source, which emits 3757) and recomputing the four artifacts + the
`completed` chain passed `replay`(16), `verify`(10), and the oracle. Re-executing the frozen source
at `slots = 3800` was independently confirmed to reproduce the committed digests exactly.

**Fix (`a7dee93`).** Added `tests/test_v2c_oq_committed_run.py::
test_committed_digests_re_derive_from_the_frozen_source`: it registers → starts → executes →
`build_oq_archive` from the isolated `pristine_oq_repo` copy of the frozen source at `slots = 3800`
and asserts the re-derived `result_sha256` / `result_bundle_sha256` equal the committed literals. A
forged result cannot pass both this and the read-back assertions unless the frozen source itself were
altered — which `verify_oq_source_freeze` independently refuses. The test is CPython-3.12-only (it
re-executes the OQ runtime); the read-only certification still covers the 3.13 leg. Verified: 3.12 →
9 passed; 3.13 → 8 passed, 1 skipped. Fix landed in the test layer because the verifier/CLI/oracle
are frozen and unmodifiable post-freeze.

## F-2 — pristine-branch replay/verify don't flag an orphaned archive — BY-DESIGN

**Raised by:** Auditor A (Finding 2, Low). Truncating `oq_registry.jsonl` to byte-empty makes the
`replay` pristine branch certify `registry_pristine_no_run_registered` while a `qualified` archive
still sits on disk; `verify` returns `checks: []` for a truncated/`started` registry. **Disposition:**
no `qualified` certification is emitted on either path, the deep verifier/oracle still hard-fail
without a `completed` event, and the one-shot budget cannot actually be reset — the orchestrator's
`no_prior_run_artifacts` gate refuses any re-register/re-start while the archive exists. A
state-consistency asymmetry, not a forgery vector. The CLI (`cli.py`) is frozen; no change.

## F-3 — fixture re-declares run-produced relpaths as literals — BY-DESIGN (fail-safe)

**Raised by:** Auditor B. `tests/conftest.py` `pristine_oq_repo` hardcodes the archive/registry/
sealed-ledger relpaths rather than importing the source constants, so a future freeze epoch that
renamed them could desync the fixture. **Disposition:** the OQ source is frozen (constants cannot
change), and a stale literal **fails safe** — a leftover archive or non-empty registry makes the
`no_prior_run_artifacts` / `registry_state_permits` gate raise, so the test fails loudly rather than
passing falsely. Not a real defect.

## F-5 — narration vocabulary regex misses zero-width / Unicode-confusable — DOCUMENT-ONLY

**Raised by:** Auditor C (Low). The secondary forbidden-term regex in the frozen `result.py` /
`oracle.py` uses `\b…\b` with `IGNORECASE` but no zero-width stripping or Unicode normalization,
unlike the firewall's own `_normalize_for_scan`. Constructed evasions (`retur​n`, `P&L`, Cyrillic
`аlpha`) pass the screen. **Disposition:** non-exploitable and document-only. The result/report are
built from code-controlled templates + numeric run measurements; no candidate- or user-controlled
free text flows in, so a term can only be planted by editing source (at which point the screen is
equally editable). The **authoritative** no-strategy gates are the structural firewall and the
numeric zero-exposure invariant — both independently re-derived and independent of vocabulary
matching. The modules are frozen and cannot be modified post-freeze. Recorded as an accepted
limitation in `docs/V2C_SECURITY.md`.

## F-6 — integrity is keyless; provenance anchored by git — BY-DESIGN (disclosed)

**Raised by:** Auditors A, C, D. There is no signing key, so the integrity chain is a keyless
`canonical_sha256`, and the OQ-E2A activation anchor records (not cryptographically attests) that
`cea86a5` carries the freeze. **Disposition:** disclosed explicitly in the freeze statement and
`docs/V2C_SECURITY.md`. Genuineness rests on the append-only hash-linked registry, write-once
publication, from-source digest re-derivation (F-1 fix), and git history. Auditor D independently
verified via git history that `cea86a5` is genuinely the freeze commit. A forgery that also rewrites
the frozen source is out of scope for the offline verifier and delegated to human git-history review.

## F-7 — branch advanced during the audit — INFORMATIONAL

**Raised by:** Auditor E (Finding 0). HEAD moved `530f182` → `6f7760e` mid-audit as the F-1 hardening
commit and the terminal-doc commits landed. **Disposition:** no action. `git diff 530f182 HEAD` over
`.github/`, `pyproject.toml`, `uv.lock`, `src/` is empty — the follow-on commits are additive docs +
one 3.12-only test. E also root-caused a transient `test_readiness` failure to the tree mutating
mid-run during its own long audit; a clean re-run at stable HEAD is fully green (3632 passed, 62
skipped, 0 failed), and CI cannot hit this because it checks out one immutable SHA.
