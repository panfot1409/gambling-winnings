# V1 private-GA independent acceptance audit (§23)

**Verdict: ACCEPTED for a private-GA merge into `main`.**

This audit certifies that the private-GA branch `release/v1.1.0-private-ga` is code-frozen, honestly
private, governance-neutral, and reproducible, and that merging it changes nothing in the accepted
research record. It is the pre-merge gate for §24 (true merge → MPGA).

## Scope

- Branch `release/v1.1.0-private-ga`, code-freeze HEAD `20e9c32` (`release_state: ready`).
- Base: `main` at `9e3beb79a2be7323aee8638dde204900ebe52a46` (MGA), the branch point.
- Package `eth-research`, version **1.1.0** (unchanged throughout the program).

## Governance neutrality — the accepted record is untouched (no Class D)

- **Governed-state digest reproduces**: `b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2`
  (every `research/` artifact hashed). `git diff main...HEAD -- research/` is empty.
- **The three sealed ledgers stay byte-empty** (sha256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`):
  `research/m2b/test_evaluations.jsonl`, `research/m3a/development_gate_access.jsonl`,
  `research/m3d/prospective_evaluations.jsonl`. Their contents were never read.
- **Governance states unchanged**: M3C rejected, M3D immature + evaluation-unauthorized, M3E ready +
  inactive (zero proposals). No development gate or final holdout was accessed.
- **Version stays `1.1.0`**; no accepted `research/mXX` artifact changed.

## Private posture — nothing public (no Class A)

- `release/v1.1.0/release_state.json`: `distribution_classification: private`,
  `repository_visibility_required: private`, `public_ga_abandoned: true`, `published: false`, every
  `public_channels_closed` flag false, `private_payload_delivered: false` (flips true only at
  `shipped`), on the ordered lifecycle `public_ga_abandoned → private_ga_in_progress → ready → shipped`.
- **No `LICENSE`/`COPYING`/SPDX file**; `pyproject.toml` declares no `[project].license` and no
  `License ::` classifier, and carries the `Private :: Do Not Upload` guard (also in the built wheel
  `METADATA`).
- **No public-publication vector** anywhere in the executable surface (`.github/workflows`,
  `.github/scripts`, `src/eth_research`, `tools`): no PyPI/TestPyPI host, `twine upload`,
  `uv publish`, `poetry`/`flit`/`hatch publish`, `gh-action-pypi-publish`, `softprops/action-gh-release`,
  public `gh release create`, `id-token: write`, or OSI classifier. Enforced by the standing kill
  switch `tests/test_public_publication_killswitch.py`.
- No public GitHub Release, no public index/registry, no OIDC publisher, no API token.

## Canonical frozen identities (register R)

Registered deterministically in `release/private/v1.1.0/private_payload_manifest.json` and
reproducible on the authoritative runner (CPython 3.12.3, uv, hatchling==1.31.0,
`SOURCE_DATE_EPOCH=1735689600`):

| Artifact | sha256 |
| --- | --- |
| source tree (`src/eth_research/**`, 215 members) | `6fa22c564f3a15817f7c948d38feb5fdd779a8079f8a0aa3080056e85568b272` |
| wheel `eth_research-1.1.0-py3-none-any.whl` | `93eb4183edb16876d5e622b384028ec2ecef151ba97afe41cb37bba3c2eb12b2` |
| sdist `eth_research-1.1.0.tar.gz` | `ab90849495a442248eb000f64bb540c86e43753ad27e77a0c5aab6d3e30454de` |
| `SHA256SUMS` | `bc1fa39fad03354087dcf2493b97e93434c2e1b619202e9b154eb97d9a9da271` |
| `provenance.json` | `4e53505c571d93460eb290799a4af4ed2b2da5952c892eafc2bc1293a5181ea2` |
| `sbom.cdx.json` | `7fd0396afbf4e642d724ea2a90ae3d25d108de5540f472fc1e73eecc11fa2731` |
| `PRIVATE_INSTALL.md` | `f8f20a850a73808869b4b1f0de84da7bdd94d834740818e57b92e19329c3d318` |
| distribution policy | `22f42d7854eec8a8f59fc37b2e1fd85e027d337d0b03ce006797c227f2e1a081` |

The deterministic payload tar `eth-research-1.1.0-private-payload.tar` rebuilds byte-for-byte on the
authoritative runner and is verified against these member hashes; binaries are not committed to Git.
`release_evidence.py --check` and `private_release.py --check` both pass at HEAD.

## Distribution (private, access-controlled)

- **Channel A — immutable Git commit**: `pip install "eth-research @
  git+ssh://git@github.com/panfot1409/gambling-winnings.git@<FULL_SHA>"` pinned to the full 40-hex
  final private-GA merge commit (branch/`main` rejected). Requires private-repo authorization.
- **Channel B — private wheel payload**: download the access-controlled Actions artifact, verify the
  payload SHA-256 + `SHA256SUMS`, unpack, clean env, install pinned deps, `pip install --no-deps` the
  wheel. Delivered only by the dispatch-only, least-privilege `private-release-build.yml` to the
  private repository's own Actions artifact store.

## Pre-merge red teams (§21) — all CLEAN

Three independent read-only red teams audited the frozen tree; after fixes each re-audited the
corrected tree and returned CLEAN. **Zero Class A (public exposure/secret) and zero Class D (governed
drift).** Six Class B/C findings were fixed failing-test-first (see
`docs/V1_PRIVATE_GA_BUG_LOG.md`): the kill switch now covers `uv publish`/build-backend publish verbs
and `.github/scripts/**`; the secret scanner detects GitHub fine-grained/GitLab/Google/Stripe/Slack-app
tokens; the license-decision doc's public-PyPI runbook was neutralized; the reproducibility doc now
honestly names the root `.gitignore` as the sdist's fourth input; and the release workflow gates the
consumer matrix and committed-manifest fidelity fail-closed.

### Acknowledged non-findings (no change required)

- `tools/scan_secrets.py`'s Google-key detector has no leading boundary anchor; verified it does not
  false-positive on the frozen, reproducible artifacts.
- Repository visibility is an external control (confirmed private out-of-band via the owner's setting;
  the private-release workflow additionally refuses to run unless `repository.private == true`).
- The kill switch does not scan `tests/`; those files deliberately contain forbidden-vector strings as
  fixtures, so scanning them would false-positive. Non-exploitable — the release build runs
  `contents: read` with no token and the executed test files are vector-free.
- `scan_distribution.py`'s suffix blocklist omits `.json`; the *positive* member allowlist already
  rejects any unexpected `.json` member.

## Merge authorization

- **True merge commit only** (no squash/rebase/fast-forward/amend/force) into `main`. Re-fetch `main`,
  verify it is unmoved from MGA and CI is terminal-green, undraft only as the immediate prerequisite.
- Branch protection requiring human review is an **external gate** — if present, the PR is left ready
  and reported; the agent does not self-approve.
- Post-merge: re-verify governed digest `b2077eaf`, the byte-empty ledgers, the private posture, and
  the reproducible payload on the merged `main`.

## Tag & delivery (§25–§26)

The unpushed local prerelease `v1.1.0` is deleted and recreated **locally only** to point at the final
merge commit; a single normal `git push origin refs/tags/v1.1.0` is attempted, and a repeated HTTP 403
is recorded as known organization tag-write policy debt (retain the local tag + branch; do not call it
published). The private payload is delivered by dispatching `private-release-build.yml` and downloading
the access-controlled artifact.

## HARD STOPs — none triggered

Repository is private; no nonempty ledger; no governed drift; no secret in any artifact; no research/
raw data in wheel/sdist/payload; no public publication; no public-capable workflow; version pinned at
1.1.0; no Class A/D finding; consumer parity across runtimes; reproducible payload; access-controlled
artifact. The only external blocker is the standing organization tag-write policy (§25), which stops
only the tag/Release path, not the private delivery.
