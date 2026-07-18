# Changelog

All notable changes to `eth-research` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is a **research-only, offline** toolkit: no live trading, no exchange or wallet connectivity, no
network access, no leverage/margin/shorting, and no alpha claim. See `README.md` and
`docs/V1_LIMITATIONS.md` for the full boundary.

> **Distribution note.** The owner decided to keep the project **private**. v1.1.0 is distributed
> **privately** to authorized repository collaborators only — **no** PyPI/TestPyPI, **no** public
> GitHub Release, **no** public registry, and **no** open-source license. The repository ships no
> `LICENSE`; project metadata authorizes no public redistribution. See
> `docs/V1_PRIVATE_GA_PLAN.md` and `docs/V1_PRIVATE_DISTRIBUTION.md`.

## [Unreleased]

- **Private GA** on `release/v1.1.0-private-ga`: private distribution policy + verifier, a deterministic
  private payload builder (wheel/sdist/SHA256SUMS/SBOM/manifest/install guide), a dispatch-only
  least-privilege private release workflow, a public-publication kill switch, and private consumer
  installation tests. The package version remains `1.1.0`. No accepted research artifact changed.
- The earlier public-GA hardening on `release/v1.1.0-ga` (packaging metadata, community/health files,
  read-only release dry-run, SBOM, checksums, release manifest/state) is retained; its *public*
  publication route (PyPI Trusted Publishing) is **superseded and abandoned** by the private decision.

## [1.1.0] — Milestone 4B: multi-asset portfolio research simulator

### Added
- An isolated, offline, deterministic **multi-asset / multi-venue / multi-currency** portfolio
  research simulator (`eth_research.portfolio`), stacked **additively** on the v1.0 single-asset
  platform: fractional target weights over a shared cash pool, causal marking with staleness,
  explicit membership and predeclared FX, a shared-cash execution-cost solver, additive
  per-asset/per-currency attribution, and a full-graph result verifier.
- Canonical JSON identities with domain-separated SHA-256; batch = streaming = checkpoint/resume
  byte-for-byte.
- The read-only `m4b-replay` CI workflow and the `research/m4b/` registration artifacts (public-API
  snapshot, reference identities, distribution manifest, source freeze).

### Guarantees
- Every accepted v1.0 public-API descriptor is byte-identical (the layer is strictly additive).
- **No** leverage, shorting, margin, derivatives, optimizer/grid/ML, network, or accepted real ETH
  dataset is used for any portfolio experiment. Long-only, cash-safe accounting.

## [1.0.0] — Milestone 4A: offline research platform

### Added
- A small, strictly-typed **public API** (`eth_research.api`): closed error taxonomy with stable
  codes/exit codes, frozen canonical value models, dataset validation/split/build, a public strategy
  protocol, two backtest entry points, an immutable `ResearchResult`, a strict `RunConfig`, a
  tamper-evident `RunReceipt`, and a transactional output publisher.
- One offline **CLI** `eth-research` (`version`/`doctor`/`demo`/`dataset`/`backtest`/`result`/
  `receipt`), deterministic `--json`, stable per-family exit codes; never prompts, colours, or
  touches the network or `$HOME`.
- Private-data-safe distribution: hatchling inclusion allowlist, a stdlib distribution scanner, a
  byte-identical reproducible double build, and an installed-wheel consumer end-to-end test.

## [0.9.0] — Milestone 3F: independent verification and deterministic recovery

### Added
- An isolated `eth_research.m3f` verification/recovery layer over the accepted research stack: a
  strict-parse / safe-path / canonical-bytes foundation, a repository freeze catalog, a byte-derived
  honest-state governance machine, a genuinely independent standard-library verifier, semantic
  oracles, and a deterministic private recovery capsule + drill. Verification-only; computes no
  strategy signal and mutates no ledger.

## Earlier (internal research milestones)

Versions `0.3.0`–`0.8.0` were internal research milestones (M2B real-data benchmarks, M3A walk-forward
evaluation, M3B fractional engine, M3C numerical-contract closure, M3D prospective-data governance,
M3E review-only prospective automation). Their design, findings, and terminal audits are recorded
under `docs/`. They were developed on the private research trunk and are summarized here for
continuity; the first versions intended for public packaging are `1.0.0` and `1.1.0`.

[Unreleased]: https://github.com/panfot1409/gambling-winnings/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/panfot1409/gambling-winnings/releases/tag/v1.1.0
[1.0.0]: https://github.com/panfot1409/gambling-winnings/releases/tag/v1.0.0
[0.9.0]: https://github.com/panfot1409/gambling-winnings/releases/tag/v0.9.0
