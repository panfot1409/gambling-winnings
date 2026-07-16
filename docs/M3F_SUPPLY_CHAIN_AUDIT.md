# Milestone 3F — supply-chain audit

M3F closes the supply chain with two committed, byte-reproducible inventories and a
fail-closed workflow scan. This document states what each covers and what it
guarantees.

## Workflow inventory (`research/m3f/workflow_inventory.json`)

`workflow_inventory.build_inventory` scans every `.github/workflows/*.yml` **and**
`*.yaml` (so a `.yaml` cannot escape a `.yml`-only scanner) and records, per
workflow: path, SHA-256, name, whether it has an explicit `permissions` block,
whether it can write contents, references secrets, contacts a market host, uploads
an artifact, is scheduled, pipes an installer, can push, or can merge/release/tag,
plus every pinned `uses:` target and whether all of them are full-SHA-pinned.

`check_inventory` **fails closed** on any of:

- no explicit `permissions` block;
- `contents: write` / `write-all` (block form, inline map, or comment-decoy);
- contacting a market host (`coinbase.com`/`coinbase.pro`);
- uploading an artifact;
- a piped installer (`curl|sh` / `wget|sh`);
- a plain or force `git push`;
- a merge / release / tag / PR-ready verb;
- any `uses:` ref not pinned to a full 40-hex commit SHA.

The M3E standing probe may remain **scheduled** but must stay read-only. All
committed workflows pass this scan; the inventory reproduces byte-for-byte from the
live workflows and is re-verified in `audit.verify_repository_freeze`
(`07_workflow_inventory`).

### What it guarantees / does not

It guarantees no committed workflow can, by static inspection, gain write
permission, push, tag, merge, pipe an installer, reach a market host, or upload an
artifact, and that every third-party action is pinned to an immutable commit. It
does **not** execute the workflows or analyze transitively what a pinned action
does at that SHA — pinning reduces, but does not eliminate, trust in the action's
author at that commit.

## Dependency inventory (`research/m3f/dependency_inventory.json`)

`dependency_inventory.build_inventory` derives deterministically from `uv.lock` +
`pyproject.toml`: the Python requirement, the direct dependencies and optional
groups, and every locked package with its exact version, source kind
(`registry`/`editable`/`url`), whether it records an sdist hash, its wheel-entry
count, and the SHA-256 of both lockfiles. It **fails closed** on a duplicate
package identity or a locked distribution with no reproducible source identity
(`source_kind == "unknown"`).

The inventory states its own limits in `provenance_note`: **lock reproducibility is
not binary provenance or signature verification, and any license metadata is
package-declared, never a legal-approval inference.** It reproduces byte-for-byte
and is re-verified in the whole-graph audit (`06_dependency_inventory`).

## CI supply chain (`.github/workflows/m3f-replay.yml`)

The replay workflow is itself minimal-trust:

- `permissions: contents: read` only — no write anywhere.
- Every action pinned to a full commit SHA (`actions/checkout@11bd71…`).
- `uv` installed from a hash-pinned PyPI wheel (`ci/uv-requirements.txt`,
  `--require-hashes --only-binary=:all:`) — no `curl | sh`.
- No artifact upload, no network beyond the pinned installer and `uv sync`.
- The **independent-verifier** job installs *nothing*, asserts `eth_research` is not
  importable, and runs the standard-library verifier — proving the independent
  path shares no dependency with the package it shadows.

## Closure statement

The accepted stack's supply chain is pinned (actions by SHA, `uv` by hash, Python
packages by lock), scanned fail-closed for write/push/tag/merge/installer/host/
artifact hazards, and re-verified byte-for-byte on every replay across CPython 3.12
and 3.13. Residual trust is limited to the pinned action authors at their pinned
commits, the PyPI artifacts at their recorded hashes, and the CPython/stdlib/git
substrate — each stated here rather than hidden.
