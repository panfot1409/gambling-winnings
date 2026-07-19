# V2A historical-replay mode for frozen v1.1.0 verifiers

When V2A opens, the active package version moves from the frozen release `1.1.0` to the V2A
development pre-release `2.0.0.dev0` (`pyproject.toml`, `src/eth_research/__init__.py`). Several
verifiers and tests were written for the v1.1.0 private-GA release and assume the *currently
installed* package version equals the frozen artifact version. Bumping the active version past
`1.1.0` would make those frozen verifiers fail — not because anything is wrong, but because the
committed v1.1.0 artifacts were built from the v1.1.0 **source tree** and cannot be byte-reproduced
from a later, diverged tree.

The historical-replay mode is the narrowly-scoped accommodation that keeps the battery honest at the
development version **without** mass-editing frozen artifacts and **without** weakening the strict
production verification that runs for a genuine v1.1.0 operation.

## The rule

Each frozen verifier reads the active version from the tracked `pyproject.toml` (`_active_version`)
and branches:

- **`active == VERSION` (a real v1.1.0 operation):** unchanged strict path — the committed artifact
  is reproduced byte-for-byte from the live source tree. This is the production path and it is
  byte-identical to its pre-V2A behavior.
- **`active != VERSION` (a later development tree, e.g. `2.0.0.dev0`):** historical-replay — the
  committed artifact is validated against *its own recorded version* and internal consistency (the
  recorded version equals the frozen `VERSION`; source anchors are structurally well-formed 64-hex
  digests and positive member counts; the governed-state baseline digest and the byte-empty sealed
  ledgers still hold). The artifact is never mutated and never regenerated.

## Exactly what changed

- **`tools/release_evidence.py`** — `check()` computes `historical = _active_version != VERSION`.
  When historical, `release_manifest.json` is verified by `_check_release_manifest_historical`
  (recorded identity + internal consistency + the version-independent governed record) instead of
  live source reproduction. `sbom.cdx.json` and `release_state.json` are version-independent
  (the SBOM excludes eth-research itself; the state is built from the `VERSION` constant) and are
  live-compared in both modes.
- **`tools/private_release.py`** — `check()` compares the committed private manifest's
  `source_tree_digest` / `source_member_count` against a live rebuild only when `active == VERSION`;
  otherwise it validates them structurally. `wheel_metadata_findings(...)` gained an optional
  keyword-only `expected_version` (default `VERSION`), so a caller verifying a *current* wheel can
  validate it against its own version while still enforcing every version-independent invariant
  (name, the `Private :: Do Not Upload` guard, license-freeness). The frozen build path
  (`build()`, `_build_wheel_and_sdist`) is **unchanged**: it still refuses any `pyproject` version
  other than `1.1.0` and still pins the wheel/sdist names to the frozen release.
- **Frozen-build tests** (the `@slow` tests that drive `_build_wheel_and_sdist` to reproduce the
  frozen v1.1.0 payload) skip when `active != VERSION` and run when `active == VERSION`. The frozen
  private-release builder produces exactly the v1.1.0 payload, so these reproduce only from the
  v1.1.0 source tree. `test_built_wheel_metadata_is_license_free_and_guarded` does **not** skip: it
  builds the current wheel and validates it against its own active version, so license-freeness and
  the upload guard stay covered at every version.

## Guarantees (honest)

1. **No frozen artifact is mutated.** No bytes under `release/`, `research/`, or the private payload
   manifest change. The v1.1.0 annotated tag and its release evidence are untouched.
2. **Strict production verification is not weakened.** At `active == VERSION` every path is
   byte-for-byte the pre-V2A strict verification. The historical branch is purely additive.
3. **The frozen builder still builds only v1.1.0.** No path lets it emit or bless a non-1.1.0
   private payload.
4. **License-freeness stays covered at every version** — at the source level by the packaging
   metadata tests (which read `pyproject.toml` directly) and at the built-wheel level by
   `test_built_wheel_metadata_is_license_free_and_guarded`.

## Evidence

- **Strict path (active == VERSION == 1.1.0):** in a disposable worktree checked out at the current
  `main` (v1.1.0) with the new tool code overlaid, `release_evidence.check` and
  `private_release.check` both return `[]` via the strict path (no historical shortcut). Verified on
  CPython 3.12.3.
- **Historical path (active == 2.0.0.dev0):** the full local battery is green on CPython 3.12.3;
  the frozen-build tests report `skipped` as historical-replay; the current-wheel license/guard test
  runs and passes.
- **Cross-version regression:** the historical path is exercised by the local 3.12.3 battery and by
  the branch CI on 3.12 and 3.13. The strict path is the unchanged pre-V2A code, already green on
  3.12 and 3.13 at the v1.1.0 commits.
