> **⛔ SUPERSEDED (2026-07-18) — public publication abandoned by owner decision.**
> The owner decided to **keep the project private**. This document is retained for historical
> accuracy: it records the *previously planned* public-GA route (PyPI Trusted Publishing, public
> GitHub Release), which is **no longer the intended completion path** and must not be executed.
> The authoritative plan is now **`docs/V1_PRIVATE_GA_PLAN.md`** and the private distribution docs
> (`V1_PRIVATE_DISTRIBUTION.md`, `V1_PRIVATE_RELEASE_OPERATIONS.md`,
> `V1_PRIVATE_RELEASE_THREAT_MODEL.md`). No public PyPI/TestPyPI/registry publication and no public
> Release will occur.

# V1.1.0 general-availability release plan

This document records the plan and posture for shipping **v1.1.0** as the first public general
availability (GA) release of `eth-research`, on branch `release/v1.1.0-ga` stacked on the merged
`main` (M3). It is additive hardening only: **no accepted research artifact under `research/mXX`
changes**, the package **version stays `1.1.0`** (this is release *packaging*, not a code bump), and
no financial formula, governance state, or sealed ledger is touched.

## Starting point

`main` contains the full accepted stack merged via three true merge commits:

| Point | Commit | Meaning | Version |
| --- | --- | --- | --- |
| M1 | `6deda20` | Milestone 3F (independent verification + recovery) | 0.9.0 |
| M2 | `5b21a20` | Milestone 4A (offline research platform v1.0) | 1.0.0 |
| M3 | `e0ba430` | Milestone 4B (multi-asset portfolio simulator v1.1, additive) | 1.1.0 |

Pre-GA governed baseline (every `research/` artifact hashed at M3): snapshot digest
`b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2` (141 artifacts). The GA branch must
reproduce this digest byte-for-byte at freeze — that is the proof GA hardening changed nothing
governed.

## What GA hardening adds (permitted roots only)

- **Packaging metadata** — `pyproject.toml` gains `[project.urls]`, PyPI classifiers (development
  status, audience, topic, typing — **no license classifier**, that is the human gate), keywords,
  authors/maintainers, and a description reframed toward *research / simulation* rather than "trading
  algorithms". Version stays `1.1.0`.
- **Community / health files** — `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SUPPORT.md`, `CITATION.cff`, plus GA docs under `docs/V1_*`.
- **Release workflows** — retire the now-obsolete `m4a-release-candidate.yml` (it hard-pins v1.0.0 and
  the frozen M4A distribution manifest, so it fails by design on the additive v1.1.0 tree), and add
  `release-dry-run.yml` (build + SBOM + checksums + private-data scan, **no publish**) and
  `publish-release.yml` (PyPI **Trusted Publishing** via OIDC, `id-token: write`, tag-triggered,
  gated on external prerequisites; never a password/token).
- **Release evidence** — under `release/v1.1.0/`: a deterministic `release_manifest.json`, a
  `release_state.json` recording the blocked-on-external-gates posture, an SBOM, SHA-256 checksums of
  the built wheel/sdist, and a reproducible-build proof.
- **Tests** — GA metadata + release-evidence hardening tests.

## Hard external gates (documented, not bypassed)

1. **License** — no `LICENSE` exists; this program will not choose one. Blocks public PyPI upload and
   any distributable GitHub Release. See `docs/V1_LICENSE_DECISION.md`.
2. **PyPI Trusted Publishing** — requires a human to configure a PyPI *pending publisher* for this
   repo/workflow; cannot be done from here.
3. **Repository/org tag-write policy** — only `v0.1.0` exists on the remote; `v0.2.0`–`v0.8.0` were
   never pushed, so tag pushes appear blocked by policy. The pipeline will *attempt* a normal atomic
   tag push and report the true result; it will not bypass policy, force-push, or fabricate tags.

## Endpoint

Freeze → draft GA PR *"Release v1.1.0: public GA hardening and publication pipeline"* (base `main`,
head `release/v1.1.0-ga`) → merge as a true merge commit (**MGA**) once all internal gates pass →
annotated tags `v0.9.0`→M1, `v1.0.0`→M2, `v1.1.0`→MGA → attempt atomic tag push → publish **only if**
every external prerequisite exists (they do not) → terminal ship report with the precise blocked
verdict and maintainer instructions. All branches and artifacts are retained.
