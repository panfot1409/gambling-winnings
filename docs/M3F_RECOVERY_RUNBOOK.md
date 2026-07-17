# Milestone 3F — recovery runbook

This runbook explains how to reconstruct and re-verify the accepted M2B–M3E
research state from the deterministic private recovery capsule, and how the
disposable-clone drill proves the capsule works before it is ever needed.

## What the capsule is

The recovery capsule is the minimal, byte-reproducible set of tracked governed
artifacts needed to rebuild and replay the accepted research state **without the
git history**: every file under `research/` except the M3F verification layer
(`research/m3f/…`, which is self-verifying and would introduce a
catalog-of-itself circularity).

The capsule **bytes are never committed** as a data publication. What is committed
is:

- `research/m3f/recovery_capsule_manifest.json` — for every capsule file, its
  `path`, `sha256`, and `byte_length`, plus a single `capsule_digest` over the
  sorted set, plus explicit flags asserting the capsule contains no
  sealed-partition contents and no secrets/credentials.
- `research/m3f/RECOVERY_CAPSULE_NOTICE.md` — the human-readable notice (also
  byte-reproducible from `bundle.render_capsule_notice`).

`bundle.build_manifest` refuses to build a capsule if any sealed ledger is
non-empty.

## Routine verification (no incident)

```
uv run --no-sync python -m eth_research.m3f.bundle --repo-root .        # manifest reproduces
uv run --no-sync python -m eth_research.m3f.recovery --repo-root . --deep  # full drill
uv run --no-sync python -m eth_research.m3f.audit --repo-root . --deep     # whole graph
python3 tools/m3f_independent_verify.py --repo-root . --json               # stdlib-only
```

The recovery drill reconstructs the capsule into a disposable temporary directory
and proves the reconstruction (a) reproduces byte-for-byte and (b) re-derives the
honest governance state and passes the semantic oracles. It then runs five failure
drills — dropped file, flipped byte, injected proposal, non-empty sealed ledger,
broken registry chain — and confirms each is detected. The committed
`research/m3f/recovery_drill.json` records the deterministic outcome (digests,
counts, booleans only).

## Reconstruction procedure (incident)

You have the manifest (from any trusted copy of `research/m3f/`) and a set of
capsule files whose provenance you want to confirm.

1. **Place the candidate files** under a fresh directory `RECOVER/` preserving
   their `research/…` paths.
2. **Re-hash against the manifest.** For each entry in
   `recovery_capsule_manifest.json`, compute `sha256(RECOVER/<path>)` and compare
   to the recorded `sha256`; confirm the byte length matches. Any missing file or
   mismatch is a failed recovery. Then recompute the `capsule_digest` over the
   sorted `path:sha256:byte_length` lines and confirm it equals the recorded
   digest. (`bundle.verify_materialized` does exactly this, using only the manifest
   — no git required, so it works on a non-repository.)
3. **Re-derive governance honesty.** Run `honest_state.derive_honest_state(RECOVER)`
   and `oracle.run_oracles(RECOVER)`. A reconstruction that re-hashes correctly but
   is not *also* governance-honest (empty ledgers, rejected verdict, immature
   cohort, zero proposals, intact registry chain, upstream provenance bindings) is
   not an acceptable recovery.
4. **Cross-check independently.** Run `tools/m3f_independent_verify.py --repo-root
   RECOVER` with a bare `python3` (no package install) to confirm the standard
   -library verifier reaches the same verdict through a separate code path.

If all four steps pass, `RECOVER/` is a faithful reconstruction of the accepted
research state.

## Failure drills (what "detected" means)

| Drill | Corruption | Detected by |
|---|---|---|
| `dropped_file` | a capsule file is missing | `verify_materialized` (missing) |
| `flipped_byte` | one file's bytes changed | `verify_materialized` (hash mismatch) + `capsule_digest` |
| `injected_proposal` | a created proposal appended to the registry | `derive_honest_state` HARD STOP |
| `nonempty_sealed_ledger` | a sealed ledger gains bytes | `derive_honest_state` HARD STOP |
| `broken_registry_chain` | a back-pointer is corrupted | `oracle.m3e_registry_chain` |

## Scope and limits

- The capsule is a **break-glass reconstruction aid and tamper-evidence bundle**,
  not a cryptographic signature or a remote attestation.
- It carries **no** sealed-partition contents (the ledgers are empty) and **no**
  secret or credential — the manifest asserts this and the build refuses a leaked
  ledger.
- Recovery re-establishes the *accepted* state only. M3F does not reconstruct,
  activate, or advance M3E; it does not fetch data or evaluate anything.
