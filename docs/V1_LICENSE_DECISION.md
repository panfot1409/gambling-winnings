> **↻ UPDATED (2026-07-18) — outcome is private distribution, not public publication.**
> The owner decided to keep the project private, so the "public publication" framing below is
> historical. The operative facts are unchanged and still hold: **no `LICENSE` exists and this program
> does not choose one.** Under a private-distribution model no public license is required; public
> redistribution remains unauthorized by project metadata regardless. Any prior "steps to clear this
> gate" that described the *abandoned* public route have been **removed** so no public-publication
> runbook remains in this file. See `docs/V1_PRIVATE_GA_PLAN.md` and `docs/V1_PRIVATE_DISTRIBUTION.md`.

# V1 license decision — external human gate

**Status: UNRESOLVED — public distribution is blocked pending a human license decision.**
This memo is a factual record, not a license grant. Nothing in this file, and nothing in the
automated GA release pipeline, chooses, adds, or implies a license.

## The fact

The repository ships **no `LICENSE`** (and no `COPYING`) file, and `pyproject.toml` declares no
`license` field and no license classifier. Under the copyright law of essentially every
jurisdiction, source published without a license is **"all rights reserved" by default**: the public
receives no grant to use, copy, modify, redistribute, or repackage it. A public GitHub repository
being *readable* is not a license to *reuse*.

## Why the release pipeline will not choose one

Selecting a license is a **decision reserved to the copyright holder** (the repository owner /
maintainers). It has legal and community consequences — permissive vs. copyleft, patent grants,
attribution requirements, warranty disclaimers — that an automated release process is not entitled to
make on the owner's behalf. This program therefore treats "no license" as an **external human gate**
and refuses to invent one, exactly as instructed.

## What this gate blocks — and what it does not

**Blocked (requires a license first):**

- Uploading the wheel/sdist to **PyPI** (or any public index). Distributing a package with no license
  gives downstream users no legal right to install and use it.
- Publishing a **GitHub Release** that attaches distributable artifacts as an official, reusable
  release of the software.

**Not blocked (proceeds now):**

- Merging the accepted research code into this repository's own `main` (already done: M1→M2→M3).
- The GA **hardening** work: metadata, community/health docs, release workflows, SBOM, checksums,
  release manifest/state, tests, and red teams.
- Creating **annotated version tags** in the repository's own history (subject only to the repo/org
  tag-write policy, which is a separate gate — see the ship report).
- Everything CI does (all read-only, `contents: read`).

Missing-license blocks **public publication only**, never the internal merge or the repository's own
version history.

## Package name (informational)

The distribution name **`eth-research`** was checked against PyPI and returned **HTTP 404** (the name
is unregistered/available as of the check). This program will **not** register a placeholder, reserve
the name, or upload anything under it — registration is part of the same publication decision that the
license gate governs.

## Public publication is abandoned (no runbook here)

An earlier draft of this memo ended with step-by-step instructions to add a license and re-enable a
public PyPI upload. Because the owner decided to keep the project **private**, that public route is
**abandoned and must not be executed**, and the actionable runbook has been **removed** so no
public-publication instructions remain in this file — mirroring the neutralization of
`docs/V1_PUBLICATION_PIPELINE.md`. There is no longer a `publish-release.yml` workflow or any
Trusted-Publishing path in the repository.

Choosing a license remains solely the copyright holder's decision and is **not** required for the
private distribution the project actually ships. If the owner ever revisits public distribution,
that is a fresh decision taken outside this program. The package is built, hardened, and privately
shippable today; public publication stays intentionally closed. See
`docs/V1_PRIVATE_DISTRIBUTION.md`.
