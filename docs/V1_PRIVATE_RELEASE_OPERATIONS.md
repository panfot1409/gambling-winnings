# V1 private release operations

How the private v1.1.0 release is built, delivered, and verified. All operations are offline except the
toolchain fetch and the access-controlled artifact transfer; none contacts a package index to publish.

## Build (deterministic, local or CI)

`python tools/private_release.py build` (see `--help`) performs, in order:

1. Require a clean tracked tree; resolve the current commit + tree.
2. Require version `1.1.0`; verify the running source equals the committed source.
3. Verify every frozen M2B–M4B artifact, the three sealed ledgers (byte-empty), and the M3C/M3D/M3E
   honest-state invariants.
4. Verify the private-distribution policy is canonical and classifies the release private.
5. Build the wheel and sdist twice into isolated temp dirs; require byte-identical names/sizes/hashes.
6. Enumerate + allowlist every archive member (reject traversal/symlink/data/research/ledger/etc.).
7. Confirm the wheel is pure Python; metadata is exactly `eth-research==1.1.0`; `Private :: Do Not
   Upload` present; no `License-Expression`/`License-File`/OSI classifier; description makes no public
   claim.
8. Generate a CycloneDX SBOM, canonical `SHA256SUMS`, an exact member manifest, an accepted-governance
   digest, a source provenance document, and a private install guide.
9. Assemble the deterministic payload `eth-research-1.1.0-private-payload.tar` with normalized
   ordering/timestamps/permissions/ownership. Dynamic run/receipt data is **excluded** from the
   deterministic payload.

`python tools/private_release.py verify` re-derives and checks all of the above from bytes.
`python tools/private_release.py --check` verifies the committed manifests are current (CI-safe,
mutates nothing).

## Deliver (private, access-controlled)

The `private-release-build.yml` workflow (manual `workflow_dispatch` only, `contents: read`, no
`id-token`/secrets/write) verifies `github.event.repository.private == true`, rebuilds the payload,
runs the fresh-consumer matrix, emits the dynamic `private_release_receipt.json`, and uploads the
closed release-output directory as a **private GitHub Actions artifact** (retention ≤ 30 days). Because
the repository is private, that artifact is downloadable only by authorized collaborators. Nothing is
uploaded to any index and no Release is created by the build workflow.

## Verify (consumer)

For each supported runtime (3.12.3 authoritative, 3.12, 3.13):

- **Channel A**: `pip install "eth-research @ git+ssh://…@<FULL_SHA>"`; then `eth-research version`
  (`1.1.0`), import the public API, run the CLI reference + doctor + the minimal portfolio reference.
- **Channel B**: download → verify payload SHA-256 + `SHA256SUMS` → unpack → clean env → install pinned
  deps → `pip install --no-deps <wheel>` → same smoke tests.

The out-of-tree consumer runs with no repository root on `PYTHONPATH` and proves the package resolves
inside the clean environment (not from the checkout).

## Canonical source of truth

The canonical private release is the **immutable private commit** plus these deterministic rebuild
instructions. The Actions artifact is a controlled delivery convenience, not the source of truth; it
can always be reconstructed byte-for-byte from the pinned commit.
