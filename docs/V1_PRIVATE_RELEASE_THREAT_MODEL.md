# V1 private release threat model

Scope: the risks specific to building and delivering the **private** v1.1.0 release. The research
firewall threat models (M3B/M3D/M3E/M3F) still apply and are unchanged.

## Assets to protect

- Governed research artifacts and the three sealed access ledgers (must never leave the repo in a
  distributed artifact and must stay byte-empty/unchanged).
- Raw market data under `data/`/`research/` (must never ride in a wheel/sdist/payload).
- Secrets/credentials of the CI environment and collaborators.
- The privacy of the repository itself (no accidental public exposure).

## Threats and mitigations

| # | Threat | Mitigation |
| --- | --- | --- |
| T1 | Governed/raw data leaks into wheel/sdist | hatchling `only-include` allowlist + `tools/scan_distribution.py` + the private-release member allowlist; tested |
| T2 | Secret/credential embedded in payload/receipt/logs | secret scanner (lexical + structural) over tree, wheel, sdist, payload, receipt, SBOM; redacted fingerprints only; a real secret is a HARD STOP |
| T3 | Local filesystem paths / runner temp paths leak | deterministic builder normalizes archives; scanner rejects home/temp paths |
| T4 | A workflow gains a public-publication path | dispatch-only least-privilege workflow; standing public-publication kill switch; workflow-security suite forbids `id-token`/secrets/write/upload except the one narrowly-allowlisted private artifact upload |
| T5 | Payload tampering between build and install | SHA-256 over payload + every member (`SHA256SUMS`); receipt binds hashes; consumer re-verifies before install |
| T6 | Non-reproducible / forged build | double build byte-identical on the authoritative runner; source-commit + tree binding; canonical rebuild from the pinned commit |
| T7 | Archive-extraction attack (traversal/symlink/zip-bomb) | member allowlist rejects traversal, absolute paths, symlinks/hardlinks/devices, duplicate/case/Unicode-collision, oversize/high-ratio members |
| T8 | Repository made public / visibility drift | builder and workflow require verified-private state; post-release red team checks visibility drift |
| T9 | Consumer accidentally imports from the checkout | out-of-tree consumer with no repo root on `PYTHONPATH`; package path proven inside the clean env |
| T10 | Access to the artifact is not actually private | the artifact is a **private-repo** Actions artifact (downloadable only by authorized collaborators); if access cannot be shown private, HARD STOP before upload |

## Non-goals / honest limits

- No cryptographic signature (Sigstore/GPG) is produced; integrity is hash-bound only.
- Cross-OS byte identity is not claimed (determinism is proven same-runner).
- Making a previously-public repo private cannot retroactively un-publish prior public history; that is
  an owner decision outside this program.
- Lexical scanning cannot prove the absence of every runtime indirection; it is paired with a closed
  file set and allowlisted workflow behavior, and the scanners state their limits.
