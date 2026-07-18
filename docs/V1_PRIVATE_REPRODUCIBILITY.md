# V1 private reproducibility contract

This document states — precisely and honestly — what byte-reproducibility `eth-research` v1.1.0
does and does not claim for its **private** distribution artifacts (the wheel, the sdist, and the
assembled private payload tar). It is the reproducibility companion to
[`V1_PRIVATE_DISTRIBUTION.md`](V1_PRIVATE_DISTRIBUTION.md) and is enforced by
`tests/test_private_reproducibility_contract.py` and `tools/private_release.py verify`.

## The claim

On the **authoritative runtime**, the wheel, the sdist, and the private payload tar are
**byte-deterministic**: rebuilding from the same pinned commit produces bit-for-bit identical
artifacts, so their SHA-256 digests match the ones recorded in
`release/private/v1.1.0/private_payload_manifest.json`.

The authoritative runtime is pinned to:

- **CPython 3.12.3** (installed by `uv python install 3.12.3`).
- **uv** as the build front-end (hash-pinned in `ci/uv-requirements.txt`).
- **hatchling==1.31.0** as the isolated build backend (`tool.uv.build-constraint-dependencies`).
- **`SOURCE_DATE_EPOCH=1735689600`** (2025-01-01T00:00:00Z), exported for **every** `uv build`
  invocation. Without it the sdist's gzip header and both archives' member mtimes capture the
  wall-clock build time and the digests drift; with it the clock is frozen and the archives are
  reproducible.

## Pure function of the source

The wheel and the sdist are a **pure function** of exactly three inputs:

- `src/eth_research/**` (the runtime package, including `py.typed`),
- `pyproject.toml`,
- `README.md`.

Nothing else in the repository can change them. `tests/`, `tools/`, `docs/`, `research/`, the
lockfile, the CI YAML, and every dotfile are excluded from the sdist by the anchored
`tool.hatch.build.targets.sdist.only-include` allowlist and are irrelevant to the wheel. The
private payload tar is in turn a pure, normalized function (sorted members, `mtime=0`, mode
`0644`, uid/gid `0`) of the wheel bytes and sdist bytes plus the deterministically rendered SBOM,
install guide, provenance, `SHA256SUMS`, and manifest — see `assemble_members` /
`normalized_tar_bytes` in `tools/private_release.py`.

## Honest limits

- **Same-runner only.** Byte identity is claimed on the authoritative runner (the pinned Linux
  toolchain above). **Cross-OS byte identity is NOT claimed**: a wheel/sdist built on macOS or
  Windows, or with a different CPython patch release or hatchling version, may differ byte-for-byte
  even though it is functionally equivalent. Reproduce on the same-runner toolchain to match the
  recorded digests.
- **Hash-bound, not signed.** Artifacts are bound by SHA-256, not by a cryptographic signature.
  Provenance documents are "operational provenance, not a cryptographic signature."
- **Third-party dependencies are out of scope.** The wheel is not standalone; numpy/pandas/pyarrow
  resolve from the consumer's configured indexes and are not vendored or re-pinned for byte
  identity here.

## The canonical anchor

The **canonical source of truth is the immutable private Git commit** (the final private-GA merge
commit) **plus the rebuild instructions in this document**. Anyone with authorized access can
reconstruct the exact artifacts from that commit on the authoritative runtime and compare digests
against the committed manifest.

The GitHub **Actions artifact is a convenience copy, not the source of truth.** It is an
access-controlled, 30-day-retained upload produced by `private-release-build.yml`; if it ever
disappears or is doubted, rebuild from the pinned commit. The manifest digests — reproducible from
source — are the authority, and the transient artifact is not.

## Rebuild and verify

```
# rebuild twice from bytes and assert the payload is byte-identical (needs uv + a clean tree)
python tools/private_release.py verify

# build-free consistency of the committed manifests (needs neither uv nor git)
python tools/private_release.py --check
```
