# V1.1.0 private general-availability plan

Milestone **V1P**. The repository owner has decided: **keep the project private.** This plan supersedes
every prior plan to publish `eth-research` publicly. There is **no** PyPI/TestPyPI publication, no
public GitHub Release, no public registry, no open-source license, and no OIDC/token publisher. The
outcome is a real, access-controlled **private** release for authorized repository collaborators.

## Starting state (verified independently)

- Repository `panfot1409/gambling-winnings`, verified **private** (`visibility: private`, updated
  2026-07-18T09:07:52Z). The owner set this externally; this program does **not** change visibility.
- `main == origin/main ==` **MGA `9e3beb79a2be7323aee8638dde204900ebe52a46`**; working tree clean.
- Version **1.1.0** (stays 1.1.0 — this is release packaging, not a code bump).
- Remote tags: only `v0.1.0`; **no remote `v1.1.0`**.
- Local annotated tags: `v0.9.0`→M1, `v1.0.0`→M2, `v1.1.0`→MGA (tag object
  `6524475d18bb39205f3cd93c938daed93656a82a`, unpushed prerelease).
- Three sealed ledgers byte-empty (`e3b0c442…`); governed baseline `b2077eaf…` reproduces.
- No `LICENSE`; `Private :: Do Not Upload` classifier present.

## Definition of "privately shipped" (§2)

v1.1.0 is privately shipped only if all hold: repository private; private-GA changes merged to `main`
via a true two-parent merge commit; final tree passes the whole battery; deterministic wheel+sdist
built from the final commit; distributions scanned free of governed/raw/ledger/credential/local-path
content; a deterministic private payload (wheel, sdist, SHA256SUMS, CycloneDX SBOM, provenance
manifest, private install guide, verification steps) is produced; the payload is delivered only through
an access-controlled channel (a private GitHub Actions artifact); a fresh authorized consumer install
succeeds; a second clean consumer reproduces the public API + CLI; no public index/release/artifact
receives any file; the final commit is installable by immutable SHA; the three ledgers stay byte-empty
throughout. A remote annotated tag + private Release are desirable but **not required** if the org's
tag-ref policy still blocks tag publication (recorded as remote-tag debt).

## License decision (§13)

The owner chose *private distribution*, not a specific proprietary license. This program therefore adds
**no** `LICENSE`/`COPYING`, no SPDX expression, no `LicenseRef-*`, no fabricated copyright holder, and
no OSI classifier. Factual wording only: no public license is declared; public redistribution is not
authorized by project metadata; distribution is operationally restricted to authorized private-repo
collaborators; legal permissions remain an owner/legal decision. `Private :: Do Not Upload` is kept.

## Prohibitions

No PyPI/TestPyPI publish; no pending publisher/OIDC/API token; no `twine`; no public package registry;
no public GitHub Release; no repository-visibility change; no collaborator/org-policy change; no license
invention; no OSI classifier; no open-source claim; no governed/raw/ledger upload; no secret exposure;
no M3E activation, M3D evaluation, gate/holdout access, ledger append, new experiment, tuning, live/
paper trading, order routing, wallet/signing/exchange auth, leverage/shorting/derivatives; no
force-push/rebase/history-rewrite; no lightweight tag; no remote-tag move.

## Private installation channels (§8)

- **Channel A — immutable private Git commit.** Authenticated `pip install "eth-research @
  git+ssh://…@<FULL_SHA>"` pinned to the final merge commit SHA (branch/`main` is not an acceptable
  reproducibility pin). Resolves third-party deps from configured indexes; no public `eth-research`.
- **Channel B — private wheel payload.** Download the access-controlled artifact, verify payload
  SHA-256 + SHA256SUMS, unpack safely, create a clean env, install pinned deps, install the wheel with
  `--no-deps`, run doctor/version/API/CLI smoke tests. The wheel is not claimed standalone (deps are
  not vendored).

## Deterministic bundle format (§6)

`eth-research-1.1.0-private-payload.tar` with normalized ordering/timestamps/permissions, containing
the wheel, sdist, `SHA256SUMS`, `sbom.cdx.json`, a source/build/provenance manifest, a private install
guide, and verification instructions. Dynamic run/receipt data stays **out** of the deterministic
payload (a separate `private_release_receipt.json` lives in the Actions artifact). Only deterministic
manifests + verification code are committed to Git; wheel/sdist/payload binaries are **not** committed.

## Access-control assumptions (§15/§26)

The repository is private, so its GitHub Actions artifacts are downloadable only by users with
authorized repository access — this is the access-controlled delivery channel. The canonical release is
the immutable private commit plus deterministic rebuild instructions; the Actions artifact is a
controlled delivery mechanism, not the source of truth.

## Tag correction procedure (§1/§25)

The current local `v1.1.0`→MGA is an **unpublished prerelease** object. The owner authorizes deleting
and recreating **only** this unpublished local tag after the final private-GA merge, pointing the new
annotated `v1.1.0` at the final merge commit. `v0.9.0`/`v1.0.0` remain unchanged. No remote tag is
moved/deleted. One normal `git push origin refs/tags/v1.1.0` is attempted; a repeated HTTP 403 is
recorded as known tag-write policy debt (retain the local tag + branch; do not call it published).

## Implementation phases

1. Plan (this doc) + supersede public-pub docs + private distribution/threat-model/operations docs.
2. Strict `private_distribution_policy.json` + stdlib verifier.
3. Deterministic `tools/private_release.py` builder + payload/receipt models + archive-member allowlist.
4. Private install docs + fresh-consumer verification matrix.
5. `private-release-build.yml` (dispatch-only, least-privilege) + narrow workflow-security exception +
   adversarial evasion matrix + public-publication kill switch.
6. Release-evidence migration + private release manifests; secret scanner; reproducibility contract;
   failure-injection matrix; full test program.
7. Code freeze E + register R; push; CI green.
8. Three independent pre-merge red teams (Class A/D = HARD STOP).
9. Draft PR + acceptance audit + merge simulation.
10. True merge → MPGA + post-merge CI green.
11. Replace local `v1.1.0` tag + push attempt.
12. Dispatch private artifact workflow + download + verify + post-release red team.
13. Terminal battery + terminal audit + 70-item handoff.

## Test matrix

Policy strictness; kill switch; deterministic builder; member allowlist; receipt parsing; workflow
security; repo-privacy contract; install docs; wheel/sdist/exact-commit consumers (3.12.3/3.12/3.13);
no-license metadata; no-publication state; secret scanner; path confinement; failure recovery;
release-state transitions; local-tag replacement; governed-state + ledger neutrality; M3C/M3D/M3E
preservation. No test touches the development gate or final holdout.

## Red-team plan

Three parallel read-only auditors — A (privacy/leakage/distribution), B (reproducibility/provenance/
consumer), C (workflow/token/governance). Class A (public exposure/secret) or D (governed drift) = HARD
STOP; Class B/C fixed failing-test-first with a bug log; all three rerun against the fixed tree.

## Merge & tag authorization

True merge commit only (no squash/rebase/ff/amend/force). Re-fetch main, verify unmoved + CI terminal
green, undraft only as the immediate prerequisite. Branch protection requiring human review is an
external gate — leave the PR ready and report. Tag replacement + one push attempt per §25.

## Terminal report

`docs/V1_PRIVATE_GA_TERMINAL_AUDIT.md` + a 70-section handoff with one of the exact honest verdicts:
`PRIVATE v1.1.0 GA SHIPPED — REMOTE TAG DEBT REMAINS` / `… REMOTE TAG AND PRIVATE RELEASE COMPLETE` /
`PRIVATE v1.1.0 GA READY — BLOCKED BEFORE PRIVATE DELIVERY` / `PRIVATE v1.1.0 GA STOPPED — INTEGRITY OR
PRIVACY FAILURE`. Never "shipped" without the `PRIVATE` qualifier.

## Hard stops (§32)

Repo not private; nonempty ledger; governed drift; secret in an artifact; raw/research data in
wheel/sdist/payload; any public publication; a public workflow that can publish; an unexpected remote
`v1.1.0` at another target; a forced version change off 1.1.0; a Class A/D finding; cross-runtime
consumer divergence; non-reproducible payload; non-private artifact access; main moves invalidating the
PR; branch protection needing human approval; tag-policy block (stops only the tag/Release path); any
action requiring org-policy bypass.

## Immutable-governance invariants

Every accepted `research/mXX` artifact byte-identical (baseline `b2077eaf…`); three sealed ledgers
byte-empty; M3C rejected; M3D immature + evaluation-unauthorized; M3E ready + inactive + zero
production proposals; no network/leverage/shorting/derivative/live-trading surface; no accepted real
dataset used.
