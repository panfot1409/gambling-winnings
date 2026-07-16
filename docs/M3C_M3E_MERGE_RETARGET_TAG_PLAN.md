# M3C–M3E Merge Simulation, Retarget & Tag Plan (for a human operator)

This document records the **proven** disposable three-merge simulation and the exact,
deterministic future human sequence to merge PR #6 → #7 → #8 and (later) tag. **Nothing
here is executed by the audit** — no merge, retarget, tag, release, or branch delete has
been or may be performed. This is a plan + evidence for a human operator.

## §18 Disposable three-merge simulation — PROVEN

In a fresh `git clone --no-local` (throwaway; not pushed), simulating `main` at `M0`
and merging each PR head with `--no-ff`:

| Merge | Commit | Parents | Tree | vs accepted head |
|---|---|---|---|---|
| main = M0 | `a7640e3` | — | `3386c1c2` | — |
| merge PR #6 (C) → MC | `8b135345` | [`a7640e3`, `c508724`] | `10aef4a7` | **== tree(C)** |
| merge PR #7 (D) → MD | `1cb3535d` | [`8b135345`, `2e5192b`] | `1cf4d384` | **== tree(D)** |
| merge PR #8 (E) → ME | `841027a2` | [`1cb3535d`, `334ba28`] | `d520eaa8` | **== tree(E)** |

Proven at the simulated merged main (`ME`):
- **`tree(ME) == tree(E) = d520eaa8…` byte-identical** — the merged main is byte-for-byte
  PR #8's accepted tree.
- Patch identity holds under retarget: `diff(C..D) == diff(MC...D)` and
  `diff(D..E) == diff(MD...E)` (identical sha256) — a real retarget of PR #7 onto merged
  main, then PR #8, reproduces the exact same change sets; nothing is duplicated or dropped.
- Every original commit (`M0`, `C`, `D`, `E`) is an ancestor of `ME`; `179` files change
  `M0..ME`, exactly matching `M0..E`.
- At `ME`: version `0.8.0`; the three sealed ledgers are byte-empty; `research/**` differs
  from `E` in **0** files; the cohort is still 3 rows through `2026-07-14`, immature; the
  M3C candidate is still `rejected_for_development_gate_promotion`.
- Because `tree(ME) == tree(E)` is byte-identical, every gate/replay at `ME` is identical
  by construction to the gates/replays already green at `E`.

## §19 Future human retarget + merge sequence (do NOT execute during the audit)

Merge commits only (never squash/rebase); verify at each step; stop on any failure.

| Step | Action | Verify |
|---|---|---|
| A | Merge PR #6 into `main` with a **merge commit** (`--no-ff`). | new `main` parent2 == `c508724`; `tree` == `tree(c508724)`. |
| B | Wait for post-merge `main` CI + M2B/M3A/M3B/M3C replays → all green. | check-suite success on the merge commit. |
| C | Retarget PR #7 base `claude/m3c-…` → `main`. | GitHub shows base `main`; **changed-files + additions/deletions unchanged** (80 files); `diff(base...head)` sha256 == the recorded `diff(C,D)` = `31cc3b67…`. |
| D | Confirm patch identity + file stats identical to pre-retarget. | `git diff <newbase>...<head>` == pre-retarget delta. |
| E | Merge PR #7 with a merge commit. | parent2 == `2e5192b`; `tree` == `tree(2e5192b)`. |
| F | Post-merge `main` CI + replays (incl. M3D) → green. | check-suite success. |
| G | Retarget PR #8 base `claude/m3d-…` → `main`. | base `main`; changed-files (55) + stats unchanged; `diff(base...head)` sha256 == recorded `diff(D,E)` = `121e23b9…`. |
| H | Confirm patch identity + stats identical. | as G. |
| I | Merge PR #8 with a merge commit. | parent2 == `334ba28`; **final `main` tree == `d520eaa8` == tree(PR #8 head)**. |
| J | Post-merge `main` CI + all six replays (M2B/M3A/M3B/M3C/M3D/M3E) → green. | check-suite success. |
| K | Verify final `main` tree equals PR #8 head tree, three ledgers byte-empty, version `0.8.0`, cohort/immaturity intact, M3C still rejected. | freeze-table verifier + `m3e.status` + `m3d.status`. |
| L | Only afterwards consider activation (see `docs/M3E_ACTIVATION_READINESS.md`). | — |

**Rollback / stop conditions:** if any post-merge CI, replay, ledger, immutable-hash, or
tree check fails, STOP and do not proceed to the next merge; a merge commit can be reverted
with a revert commit (never force-push/reset a shared branch). Because the deltas are
patch-identical under retarget, a failed retarget indicates an environment/CI problem, not
a content conflict — investigate before retrying.

## §20 Future annotated tag plan (do NOT create tags during the audit)

Only **annotated** tags at the future merge commits (no lightweight tags, no GitHub Release
fallback). Current remote tags: only `v0.1.0` (no `v0.6.0`/`v0.7.0`/`v0.8.0`).

| Tag | Target | Expected version | Required before tagging | Annotated message (suggested) |
|---|---|---|---|---|
| `v0.6.0` | future PR #6 merge commit on `main` | `0.6.0` | post-merge `main` CI + M3C replay green; gate+holdout ledgers byte-empty | "M3C — one preregistered candidate, executed once, rejected; sealed ledgers untouched." |
| `v0.7.0` | future PR #7 merge commit | `0.7.0` | post-merge CI + M3D replay green; three ledgers byte-empty; cohort immature | "M3D — prospective cohort immature (3/365), no strategy evaluated." |
| `v0.8.0` | future PR #8 merge commit | `0.8.0` | post-merge CI + all six replays green; three ledgers byte-empty; 0 proposals | "M3E — review-only update automation ready, not active; no strategy evaluated." |

For each tag, after creation the operator should verify the **peeled** ref
(`git ls-remote --tags origin v0.x.0^{}`) resolves to the intended merge commit and that
`git show v0.x.0` reports the annotated message. **Tag-write may be restricted by org
policy** (this repo currently exposes only `v0.1.0` despite later versions existing on
branches — i.e. prior milestone tags were not pushable); if `git push origin v0.x.0` is
rejected, that is an org tag-write restriction to resolve with a maintainer, **not** a
reason to fall back to a lightweight tag or a Release.

## Absolute constraint

This plan is documentation. The audit performs **no** merge, retarget, tag, release, or
branch operation. Executing any step above is a separate, human-authorized action.
