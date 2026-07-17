# Milestone 4B — terminal acceptance audit

**Milestone:** M4B, the multi-asset, multi-venue, multi-currency portfolio research simulator —
an isolated, offline, deterministic research layer stacked *additively* on the accepted Milestone 4A
single-asset platform. **Package version:** 1.1.0. **Branch:** `claude/m4b-multi-asset-portfolio-simulator`.
**Base (unmerged, draft):** `claude/m4a-offline-research-platform-rc`.

**Verdict:** the milestone is complete and internally consistent. The additive v1.1 portfolio layer
is deterministic and reproducible, the E→R→P→Q freeze is registered and verified, the independent
red teams' findings are fixed with regression tests, every accepted artifact is byte-for-byte
unchanged, the three sealed governance ledgers are byte-empty, and no hard stop (§47) was triggered.
This audit is a read-only record; it merges, undrafts, retargets, tags, releases, or deletes nothing.

## 1. What M4B is (and is not)

M4B makes the accounting, causality, and provenance of a multi-asset **long-only** rebalance
auditable over synthetic or caller-supplied local evidence. It supports fractional target weights
over a shared cash pool with **no leverage, shorting, margin, or derivatives**; it never contacts a
network, an exchange, a wallet, or a broker; every artifact it emits is canonical JSON with a stable
domain-separated SHA-256. It is a research instrument, not a trading system, and makes **no alpha
claim** — its three reference policies (`cash`, `static_equal_weight`, `static_declared_weights`)
exist to exercise the machinery against hand-computable numbers. See `docs/M4B_LIMITATIONS.md` for
the full, unsoftened boundary and `docs/M4B_DESIGN.md` for the architecture.

## 2. The E→R→P→Q freeze

| Phase | Meaning | State |
| --- | --- | --- |
| **E** — source freeze | all source/tests/docs final, suite green, red teams done, prior artifacts unchanged, version 1.1.0 | committed at `5e0de6d`; CI green |
| **R** — deterministic registration | `research/m4b/` artifacts registered from code; no executable-source change E..R | committed at `6ceca6c`; M4B Replay green |
| **P** — proof run | synthetic reference scenarios only (reference / compatibility / batch–streaming / checkpoint / distribution proofs); no accepted real dataset | proven green (see §5) |
| **Q** — post-proof red team + terminal docs | adversarial pass over the new registration surface; terminal documentation | committed at `ac13bb4` (R-Q1 fix); this audit |

The R-phase registers, under `research/m4b/`, the additive layer without committing a binary or
contacting a network (`src/eth_research/portfolio/registration.py`, `.../cli_reference.py`):

- `public_api.json` — the additive v1.1 public-API snapshot (every accepted v1.0 descriptor
  byte-identical; the milestone only adds new value models and pure functions);
- `cli_reference.txt` — the offline CLI help, pinned to CPython 3.12;
- `reference_universe.json`, `reference_protocol.json` — the synthetic reference identities;
- `reference_expected_results.json` — the pinned reference run identity (see §4);
- `distribution_manifest.json` — every portfolio-subpackage member with its content hash;
- `source_freeze.json` — binds every committed M4B artifact, the six accepted M4A v1.0 artifacts
  (proving additivity / no drift), and the three sealed ledgers (proving they stay byte-empty).

Each verifier fails closed on drift (`registration --check`, `cli_reference --check`,
`public_api --check`), and all three run in the read-only `m4b-replay` workflow on the authoritative
CPython 3.12.3.

## 3. Independent red teams (§41) and the post-freeze pass (§42 Q)

Three independent read-only red teams (accounting/causality, provenance/forgery,
security/governance/isolation) audited the pre-freeze package. The accounting core held to machine
precision under a 400-run randomized multi-asset fuzz (worst relative equity-identity error 2.7e-16;
cash and quantities never negative; gross exposure ≤ 1; hold-step residual exactly 0), and the
security / isolation / additivity boundary held (a 668-file manifest was identical before and after
all probes, the three ledgers stayed byte-empty, the M4A snapshot was unchanged, and the v1.1 API is
byte-additive over v1.0). Seven genuine but non-hard-stop findings were fixed, each with a regression
test that fails on the pre-fix code; the post-freeze Q pass found and fixed one more. Full detail and
reproductions are in `docs/M4B_BUG_LOG.md`.

| ID | Severity | Summary | Fix |
| --- | --- | --- | --- |
| R-B1 | HIGH | verifier + checkpoint did not bind trading calendars (forgeable field; wrong-calendar certification) | bind calendars into the run canonical, cross-check build/verify, bind checkpoint `calendars_fingerprint` |
| R-B2 | MEDIUM | verify left `base_currency` / `package_version` unbound | bind both to the run / running package |
| R-A1 | MEDIUM | corporate-action refusal window missed the terminal marking bar | refuse up to the terminal marking-bar close per instrument |
| R-A2 | LOW | `sortino_ratio` finite for a single-event run | gate dispersion ratios on n ≥ 2 |
| R-A3 | LOW | `annualized_return` emitted absurd-but-finite values | cap magnitude, report None for meaningless extrapolation |
| R-C1 | LOW–MED | offline-tests firewall scanned by filename prefix, missing a portfolio test | scan every portfolio-importing test, explicit narrow allowlist |
| R-C2 | INFO | AST-scan docstring overclaimed a lexical lint as structural proof | soften wording, add indirection lint |
| R-Q1 | LOW | a deleted source-freeze-bound artifact raised a raw `OSError`, not drift | wrap bound reads so a missing artifact is `RegistrationDriftError` |

## 4. The frozen reference identity

The synthetic reference run reproduces byte-exactly from a fresh build and is pinned in
`research/m4b/reference_expected_results.json`:

- `result_id` = `1ae39105c44dee034771c5d5ddbddfb0bc273131350ff5c45821021d88c96f4b`
- `terminal_equity` = 125276.83556294517, `num_fills` = 5, `event_count` = 3
- `universe_fingerprint` = `4962e3c1…`, `run_result_fingerprint` = `638c5aa3…`,
  `trace_commitment_id` = `8451093f…`

`registration --check` and `test_reference_expected_results_match_a_fresh_run` reproduce this
identity from code; the offline replay verifier proves batch = streaming = checkpoint/resume
byte-for-byte and that the result artifact builds and verifies.

## 5. Terminal criteria (§45) — verified

- **Full local battery green:** ruff (lint + format), mypy strict over `src`/`tests`/`examples`
  (424 files), and the complete `pytest` suite all pass.
- **Both consumers pass, out of tree:** the accepted M4A v1.0 CLI consumer (`test_consumer_e2e.py`)
  and the M4B v1.1 portfolio consumer (`test_m4b_consumer_e2e.py`) build the wheel, install it
  non-editable into a throwaway venv, and drive the public API from a working directory outside the
  repository with the repository source off `sys.path`.
- **Distribution safe + reproducible:** the wheel/sdist carry no private data and a double build is
  byte-identical (`test_packaging.py`).
- **Accepted artifacts unchanged:** `git diff` of `research/m4a`, `research/m3c`, `research/m3d`,
  `research/m3e` against the M4A base is empty; `source_freeze.json` binds the six accepted M4A
  artifacts by hash.
- **Sealed ledgers byte-empty** (before and after): the three governance ledgers all hash to
  `e3b0c442…` (the empty-file SHA-256).
- **Governance state unchanged:** M3C rejected, M3D immature / evaluation-unauthorized / evaluation
  ledger 0 bytes, M3E inactive, zero production proposals.
- **No forbidden capability:** no network / leverage / short / margin / derivative / dynamic-strategy
  surface; no accepted real ETH dataset used for any M4B experiment; no tag created (the eight tags
  are prior-milestone releases; no `v1.1*` tag exists).
- **Clean and pushed:** working tree clean; local `HEAD` = `origin/claude/m4b-multi-asset-portfolio-simulator`.

## 6. Hard-stop attestation (§47)

No hard stop was triggered. In particular: accepted identity is provable and unchanged; no M4A
Class-A defect affects accepted outputs; no Class-D change; no sealed ledger is nonempty or changed;
no accepted artifact changed; no M3C/M3D/M3E state changed; no production proposal, gate/holdout
access, accepted-real-data strategy run, or prospective fetch occurred; nothing required network,
credentials, leverage, shorting, a derivative, or borrow; no private artifact was packaged or
uploaded; no write-capable workflow, force-push, history rewrite, or tag bypass was used; the
accounting stays long-only and cash-safe with no weakened invariant; cross-runtime replay is exact on
structural/provenance/accounting identities with only a narrow, named, tested binary64 ULP tolerance
on value fields; and the source-freeze identity is recoverable from `source_freeze.json`. The
red-team findings above were ordinary software defects, not hard stops.

## 7. Final posture (§49)

A **draft** stacked pull request is opened with base `claude/m4a-offline-research-platform-rc` and
head `claude/m4b-multi-asset-portfolio-simulator` (never `main`). Nothing is merged, undrafted,
retargeted, tagged, released, published, or deleted. PR #9 (M3F), PR #10 (M4A), and the M4B PR all
remain open drafts. This is the ABSOLUTE FINAL STOP for Milestone 4B.
