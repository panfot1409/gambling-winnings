# V1 private-GA terminal audit & handoff (§29, §33)

**Terminal verdict: `PRIVATE v1.1.0 GA SHIPPED — REMOTE TAG DEBT REMAINS`.**

`eth-research` v1.1.0 has been shipped as a **private, access-controlled** general-availability
release for authorized collaborators of the **private** repository `panfot1409/gambling-winnings`.
The private-GA branch was merged into `main` as a true merge commit, all required CI is
terminal-green, the deterministic private payload was built and delivered on an independent GitHub
runner to the private repository's own access-controlled Actions artifact store and verified
member-exact, and three independent post-release red teams returned CLEAN. **Nothing was published
publicly.** The single outstanding item is the remote annotated tag `v1.1.0`, which the organization
tag-write policy refuses (HTTP 403) — retained locally as documented debt, and never called
"published".

This is a **private** release. It is **not** open source, **not** on PyPI/TestPyPI, has **no**
public GitHub Release, **no** public registry entry, and **no** license grant. "Shipped" here means
*private delivery occurred* — it does not mean any public availability.

## Canonical identities (register R — frozen, reproducible)

| Thing | Value |
| --- | --- |
| Package / version | `eth-research` **1.1.0** (unchanged across the entire program) |
| Public-GA merge (branch point, MGA) | `9e3beb79a2be7323aee8638dde204900ebe52a46` |
| **Private-GA merge (MPGA)** | `61aa6aea6c666db71fe63d18a102e5502ccd17e7` |
| tree(MPGA) | `1c254994a48e7378474b439cbcc516517131a8d2` |
| Governed-state digest (`research/**`) | `b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2` |
| Sealed-ledger sha256 (byte-empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| wheel `eth_research-1.1.0-py3-none-any.whl` | `93eb4183edb16876d5e622b384028ec2ecef151ba97afe41cb37bba3c2eb12b2` |
| sdist `eth_research-1.1.0.tar.gz` | `ab90849495a442248eb000f64bb540c86e43753ad27e77a0c5aab6d3e30454de` |
| `SHA256SUMS` | `bc1fa39fad03354087dcf2493b97e93434c2e1b619202e9b154eb97d9a9da271` |
| `provenance.json` | `4e53505c571d93460eb290799a4af4ed2b2da5952c892eafc2bc1293a5181ea2` |
| `sbom.cdx.json` | `7fd0396afbf4e642d724ea2a90ae3d25d108de5540f472fc1e73eecc11fa2731` |
| `PRIVATE_INSTALL.md` | `f8f20a850a73808869b4b1f0de84da7bdd94d834740818e57b92e19329c3d318` |
| deterministic payload tar (double-build identical) | `b36430544125dfa5828dcaa5a808b4163e7b8ef4b12ccc17b9e0709830f43b3c` |

## What happened, in order

1. **Merge (§23–24).** PR #13 (`release/v1.1.0-private-ga` → `main`) was merged as a **true merge
   commit** → MPGA `61aa6ae` (two parents: MGA `9e3beb79` + branch tip `ee9f402`;
   `tree(MPGA) == tree(ee9f402) == 1c254994`). Post-merge governed neutrality re-verified on `main`.
2. **Post-merge CI (§24) — all nine workflows terminal-green** for head\_sha `61aa6ae`:
   `CI` (jobs `checks (3.12)`, `checks (3.13)`, `readiness`, `authoritative-runtime` incl. the
   never-skip end-to-end lifecycle) + `M2B/M3A/M3B/M3C/M3D/M3E/M3F/M4B Replay`. The `M3F` whole-graph
   verifier passed with the new private-release workflow registered in the inventory.
3. **Tag (§25).** The unpushed local prerelease `v1.1.0` was deleted and recreated **locally only**
   as an annotated tag pointing at MPGA `61aa6ae`. A single `git push origin refs/tags/v1.1.0`
   returned **HTTP 403** (organization tag-write policy). Not a network error → not retried. The
   local tag is retained; the remote still carries only `v0.1.0`. Recorded as **tag-write policy
   debt**; not "published".
4. **Private payload delivery (§26).** `private-release-build.yml` was dispatched on `main`
   (`workflow_dispatch`, `source_commit=61aa6ae`). Run completed **success** (all 16 steps green),
   including "the private payload is byte-deterministic and reproduces the committed manifest" and
   the fail-closed "fresh-consumer install matrix must execute (never skip)". It uploaded **only**
   the closed `dist_private/` payload to this **private** repository's own access-controlled Actions
   artifact store: artifact `eth-research-1.1.0-private-payload-61aa6aea…` (1,359,192 bytes, GitHub
   zip digest `sha256:c58e2c42…`, 30-day retention, not expired).
5. **Payload verification (§26).** The payload was **independently reproduced locally** (byte-exact
   across two builds; tar `b3643054…`) and every content member matched the register-R canonical
   identity **and** the committed `release/private/v1.1.0/private_payload_manifest.json`: wheel
   `93eb4183…`, sdist `ab908494…`, `SHA256SUMS` `bc1fa39f…`, `provenance.json` `4e53505c…`,
   `sbom.cdx.json` `7fd0396a…`, `PRIVATE_INSTALL.md` `f8f20a85…`; the payload's embedded manifest is
   byte-identical to the committed one. **Environment limitation (honest):** this session's
   organization egress policy blocks the Azure blob host that serves Actions-artifact bytes
   (proxy `403 CONNECT`), so the artifact bytes could not be pulled into this session. Integrity is
   therefore established by (a) the workflow's own green reproduce-and-upload on an independent
   runner and (b) the local member-exact deterministic reproduction — not by re-hashing the pulled
   zip. Authorized collaborators on an unrestricted network download it normally from the private
   Actions run.
6. **Ship-state advance.** With private delivery complete, the lifecycle was advanced
   `ready → shipped` (`release_state_index 2 → 3`, `private_payload_delivered false → true`) via the
   `RELEASE_STATE` constant + regenerated `release_state.json`. `published` stays **false** and every
   `public_channels_closed` flag stays **false**. `release_evidence.py --check` and
   `private_release.py --check` both pass.
7. **Post-release red teams (§28) — all CLEAN.** Three independent read-only auditors:
   **A** (privacy/public-exposure), **B** (payload leakage/governed drift/reproducibility),
   **C** (workflow/token/terminal-claim honesty). **Zero Class A** (public exposure / secret),
   **zero Class D** (governed drift), **zero Class B/C**. Each independently reconfirmed the governed
   digest `b2077eaf`, the byte-empty ledgers, version 1.1.0, the member-exact reproducible payload,
   the least-privilege dispatch-only workflow, and that no doc falsely claims the tag was pushed or
   that anything was publicly published.

## Governance neutrality — the accepted record is untouched

- `git diff 9e3beb79..61aa6aea -- research/` is **empty**; the governed digest reproduces
  `b2077eaf…` (recomputed independently over 141 `research/` artifacts). The two `src/eth_research`
  files that changed in the merge are `m3e/verify_m3e_program.py` and `m3f/workflow_inventory.py`
  (the latter registers the private-release workflow) — neither is a `research/` artifact.
- The three sealed ledgers stay **byte-empty** (`e3b0c44…`) and their contents were never read:
  `research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`,
  `research/m3d/prospective_evaluations.jsonl`.
- Governance states unchanged: M3C rejected; M3D immature + evaluation-unauthorized; M3E ready +
  inactive (zero proposals). No development gate or final holdout was accessed. Version stays 1.1.0.

## Privacy posture — nothing public

- No `LICENSE`/`COPYING`/SPDX file; `pyproject.toml` declares no `[project].license` and no
  `License ::` classifier and carries `Private :: Do Not Upload` (also in the wheel `METADATA`).
- No public-publication vector anywhere in the executable surface (`.github/workflows/**`,
  `.github/scripts/**`, `src/eth_research/**`, `tools/**`) — enforced by the standing kill switch
  `tests/test_public_publication_killswitch.py`.
- `release/v1.1.0/release_state.json`: `distribution_classification: private`, `published: false`,
  every `public_channels_closed` flag false, `private_payload_delivered: true`,
  `release_state: shipped`.
- `private-release-build.yml` is `workflow_dispatch`-only, `permissions: contents: read`, no
  `id-token`/OIDC, no secret reference, SHA-pinned actions, asserts `repository.private == true`, and
  uploads only to the private Actions store. No public Release, index, or tag is ever created.

## How authorized collaborators install (private, access-controlled)

- **Channel A — immutable Git commit (durable, canonical source of truth).** Requires private-repo
  authorization; pins the full 40-hex private-GA merge commit:
  `pip install "eth-research @ git+ssh://git@github.com/panfot1409/gambling-winnings.git@61aa6aea6c666db71fe63d18a102e5502ccd17e7"`
- **Channel B — private wheel payload (re-buildable convenience copy).** Download the
  access-controlled Actions artifact from the private run, verify the payload SHA-256 + `SHA256SUMS`,
  unpack, install pinned deps, then `pip install --no-deps eth_research-1.1.0-py3-none-any.whl`. The
  artifact has 30-day retention; re-dispatch `private-release-build.yml` to refresh it. See
  `PRIVATE_INSTALL.md` and `docs/V1_PRIVATE_DISTRIBUTION.md`.

## Outstanding items / owner follow-ups (none block private delivery)

1. **Remote tag `v1.1.0` (policy debt).** The organization tag-write policy returns HTTP 403 on tag
   push. The annotated tag exists locally at MPGA. If/when policy permits, an owner with tag-write
   rights can `git push origin refs/tags/v1.1.0`. Until then the immutable commit (Channel A) is the
   canonical anchor; the missing remote tag does **not** affect private installability.
2. **Record `shipped` on `main`.** This handoff advances the lifecycle to `shipped` on branch
   `claude/eth-trading-research-setup-cux72m`; `main` remains at `ready`. No pull request was opened
   (none was requested). Merging this branch would record `shipped` + `private_payload_delivered`
   on `main`; the private delivery itself already occurred from `main@MPGA`.
3. **Payload freshness.** The Channel-B artifact expires 30 days after the build; re-dispatch the
   workflow to regenerate the byte-identical payload on demand.

## HARD STOPs — none triggered

Repository is private; no nonempty ledger; no governed drift (`b2077eaf` reproduces); no secret in
any artifact (`scan_secrets` clean); no `research/` or raw data in the wheel/sdist/payload; no public
publication; no public-capable auto-running workflow; version pinned at 1.1.0; three post-release red
teams CLEAN. The only external blocker is the standing organization tag-write policy, which stops the
remote tag only — not the private delivery.

## 70-point terminal handoff checklist (every item independently verified)

**Identity & version**
1. Package is `eth-research`; version is exactly `1.1.0` in `pyproject.toml`.
2. `src/eth_research/__init__.py` `__version__ == "1.1.0"`.
3. Version was never bumped during private GA (matches MGA and the whole program).
4. Private-GA merge commit MPGA = `61aa6aea6c666db71fe63d18a102e5502ccd17e7`.
5. MPGA is a **true merge commit** with two parents (MGA `9e3beb79` + branch tip `ee9f402`).
6. `tree(MPGA) == tree(ee9f402) == 1c254994a48e7378474b439cbcc516517131a8d2`.
7. `origin/main` is at MPGA `61aa6ae`.
8. Handoff branch `claude/eth-trading-research-setup-cux72m` descends from `origin/main` (MPGA).

**Governance neutrality (no Class D)**
9. `git diff 9e3beb79..61aa6aea -- research/` is empty (no accepted artifact changed).
10. Governed-state digest reproduces `b2077eaf…` via the tool.
11. Governed-state digest reproduces `b2077eaf…` via an independent recompute (141 files).
12. `research/m3a/development_gate_access.jsonl` is byte-empty (`e3b0c44…`).
13. `research/m2b/test_evaluations.jsonl` is byte-empty (`e3b0c44…`).
14. `research/m3d/prospective_evaluations.jsonl` is byte-empty (`e3b0c44…`).
15. No sealed-ledger contents were ever read (hash-only).
16. M3C remains rejected; M3D immature + evaluation-unauthorized; M3E ready + inactive.
17. No development gate or final holdout was accessed or evaluated.
18. `src/eth_research` merge delta is only `m3e/verify_m3e_program.py` + `m3f/workflow_inventory.py`.

**Privacy posture (no Class A)**
19. No `LICENSE`/`COPYING`/SPDX/OSI file anywhere in the tree.
20. `pyproject.toml` declares no `[project].license`.
21. `pyproject.toml` declares no `License ::` classifier.
22. `pyproject.toml` carries the `Private :: Do Not Upload` guard.
23. Wheel `METADATA` carries the `Private :: Do Not Upload` guard.
24. `release_state.json` `distribution_classification == "private"`.
25. `release_state.json` `published == false`.
26. Every `public_channels_closed` flag is false (pypi, testpypi, public release, registry,
    open-source-claim, license-present).
27. No public-publication vector in `.github/workflows/**`, `.github/scripts/**`,
    `src/eth_research/**`, `tools/**` (kill switch passes).
28. No `id-token: write` in any workflow that runs automatically (push/PR/schedule).
29. `tools/scan_secrets.py` reports a clean scan over the whole tree.
30. No doc affirmatively claims the project is open source / on PyPI / publicly available.

**Merge & CI (§24)**
31. `CI` run `29647928177` for MPGA is `success`.
32. `CI` job `checks (3.12)` is `success`.
33. `CI` job `checks (3.13)` is `success`.
34. `CI` job `readiness` is `success`.
35. `CI` job `authoritative-runtime` is `success` (incl. the never-skip E2E lifecycle step).
36. `M2B/M3A/M3B/M3C Replay` all `success` for MPGA.
37. `M3D/M3E Replay` both `success` for MPGA.
38. `M3F Replay` (whole-graph verifier) `success` for MPGA with the new workflow registered.
39. `M4B Replay` `success` for MPGA.
40. All nine push-triggered workflows for MPGA are terminal-green; none pending/failed.

**Tag (§25)**
41. Local annotated `v1.1.0` points at MPGA `61aa6ae` (`v1.1.0^{commit}`).
42. The tag is annotated (not lightweight) and its message states the private, unpublished posture.
43. `git push origin refs/tags/v1.1.0` returned HTTP 403 (org tag-write policy).
44. The 403 is a policy denial, not a network error → not retried.
45. Remote carries only `refs/tags/v0.1.0`; no remote `v1.1.0` exists.
46. The local tag is retained; the debt is documented and never called "published".

**Private payload build & delivery (§26)**
47. `private-release-build.yml` run `29648277940` (workflow_dispatch on `main`) is `success`.
48. It asserted `repository.private == true` before building.
49. It resolved and pinned `source_commit == 61aa6ae` (equals checked-out, ancestor of origin/main).
50. "Sealed ledgers byte-empty" step passed on the runner.
51. "Committed release evidence and private manifests reproduce from the tree" step passed.
52. "Private payload is byte-deterministic and reproduces the committed manifest" step passed.
53. "Fresh-consumer install matrix must execute (never skip)" step passed (wheel/sdist/commit ×
    {3.12.3, 3.13}).
54. It uploaded only `dist_private/` to the private repo's Actions artifact store.
55. Artifact `eth-research-1.1.0-private-payload-61aa6aea…` exists, 1,359,192 bytes, not expired.
56. Artifact GitHub zip digest is `sha256:c58e2c42…`; retention 30 days.
57. The run requested no `id-token`, referenced no secret, used a read-only token.
58. No public index push, public Release, or tag creation occurred in the run.

**Payload verification (§26)**
59. Local deterministic rebuild produced payload tar `b3643054…`.
60. Two independent local builds are byte-identical (determinism confirmed).
61. Rebuilt wheel sha256 == `93eb4183…` (register R + committed manifest).
62. Rebuilt sdist sha256 == `ab908494…`.
63. Rebuilt `SHA256SUMS`/`provenance.json`/`sbom.cdx.json`/`PRIVATE_INSTALL.md` all match register R.
64. Committed `private_payload_manifest.json` lists exactly these six member hashes.
65. The payload's embedded manifest is byte-identical to the committed manifest.
66. Distribution carries only `eth_research/**` + `pyproject.toml`/`README.md` (+ benign
    `.gitignore`/PKG-INFO/dist-info); no `research/`, data, ledger, `.json`/`.csv`, or secret member.

**Ship-state, red teams, battery & delivery honesty**
67. `release_state == "shipped"`, `release_state_index == 3`, `private_payload_delivered == true`,
    with `published == false` and all public channels closed; both `--check`s pass.
68. Post-release red teams A, B, C all returned CLEAN (zero Class A, zero Class D, zero Class B/C).
69. The full offline terminal battery passes on the authoritative runtime (and branch CI is green).
70. Delivery honesty: private payload delivered + verified; remote tag is documented 403 debt; the
    egress-blocked artifact byte-download is disclosed; nothing is claimed as publicly published.
