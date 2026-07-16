# Recovery capsule notice (Milestone 3F)

The recovery capsule is a private, deterministic reconstruction bundle: the
minimal set of tracked governed artifacts needed to rebuild and replay the
accepted M2B-M3E research state without the git history. Its **bytes are never
committed** as a data publication — only the manifest
(`recovery_capsule_manifest.json`) that pins every file's path, SHA-256, and
length together with a single `capsule_digest`. From that manifest the capsule
rebuilds from the working tree and verifies byte-for-byte, and the
disposable-clone drill confirms the reconstruction re-derives the honest
governance state.

## What the capsule excludes

- The M3F verification layer (`research/m3f/`) — it is self-verifying and would
  introduce a catalog-of-itself circularity.
- Generated data and reports (`data/`, `reports/`) and workflows (`.github/`).

## What the capsule guarantees it does *not* contain

- Sealed-partition contents: the three access ledgers are byte-empty and the
  manifest refuses to bundle a non-empty one.
- Secrets or network credentials of any kind.

The capsule is a break-glass reconstruction aid and tamper-evidence bundle, not
a cryptographic signature or a remote attestation.
