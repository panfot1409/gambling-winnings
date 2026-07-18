# V1 publication pipeline — SUPERSEDED (public route abandoned)

> **⛔ SUPERSEDED (2026-07-18).** The owner decided to **keep the project private**. The public
> publication pipeline this document previously described — a PyPI Trusted-Publishing (OIDC) workflow
> and a public GitHub Release — is **abandoned and must not be executed.** The actionable OIDC workflow
> template and the "steps to publish to PyPI" runbook have been **removed** from this file so no
> public-publication vector remains here. The authoritative path is now private distribution.

## What this used to be (historical, non-actionable)

During the earlier public-GA program, this document proposed publishing `eth-research` to the public
PyPI index via an OIDC Trusted-Publishing workflow, gated behind three prerequisites (a chosen license,
a configured index publisher, and a governance relaxation to permit an `id-token` workflow). None of
that was ever executed: no public index publisher was configured, no license was chosen, and no
publication workflow was ever made live. The three annotated tags were never pushed (organization
tag-write policy returned HTTP 403).

## Why it is abandoned

The owner's governing decision is to keep the repository and its distribution **private**. Public
publication of any kind is now prohibited (see `docs/V1_PRIVATE_GA_PLAN.md` §31 and the standing
public-publication kill switch enforced by the test suite). There is therefore no public pipeline to
document.

## The private replacement

- **`docs/V1_PRIVATE_DISTRIBUTION.md`** — the private distribution model and the two authorized
  channels (immutable Git commit pin; access-controlled private wheel payload).
- **`docs/V1_PRIVATE_RELEASE_OPERATIONS.md`** — how the private release is built, delivered, and
  verified.
- **`docs/V1_PRIVATE_RELEASE_THREAT_MODEL.md`** — the privacy/leakage threat model.
- **`.github/workflows/private-release-build.yml`** — a dispatch-only, least-privilege workflow that
  builds and uploads the payload as a **private** GitHub Actions artifact (no public destination, no
  `id-token`, no secret, no upload to any index).

No public index, public registry, or public GitHub Release is part of the private pipeline.
