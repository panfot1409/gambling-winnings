# Private release directory — eth-research 1.1.0

Committed, source-derived control documents for the **private** GA distribution of
`eth-research` 1.1.0. Nothing here is published to a public index or registry; the package
is unlicensed and carries the `Private :: Do Not Upload` guard.

## Committed files

- `private_distribution_policy.json` — the closed private-distribution posture (accepted vs forbidden channels,
  public-publication booleans pinned false, required governed-state / ledger anchors).
- `private_payload_manifest.json` — the registered payload manifest: per-member SHA-256 (excluding the payload
  tar and the manifest itself) plus the governed-state digest, sealed-ledger triple, policy
  SHA-256, and the `src/eth_research` member tree digest.
- `private_install_contract.json` — the two authorized install channels and the pinned runtime dependencies.

`provenance.json` and `PRIVATE_INSTALL.md` are generated deterministically into the payload by the
builder and are not committed.

## Rebuild / verify

```
# build-free consistency gate (what CI runs; needs neither uv nor git)
python tools/private_release.py --check

# assemble the deterministic payload under dist_private/ (needs uv; clean tracked tree)
python tools/private_release.py build

# rebuild twice from bytes and assert the payload is byte-identical
python tools/private_release.py verify

# regenerate these committed deliverables (maintainer)
python tools/private_release.py write-manifests
```
