# V1 publication pipeline

This describes how `eth-research` v1.1.0 would be published, and the **three independent gates** that
currently keep public publication closed. The GA hardening builds and verifies everything that does
*not* require crossing those gates.

## The three publication gates (all must be cleared by a human)

1. **License gate.** No `LICENSE` exists and this program will not choose one
   (`docs/V1_LICENSE_DECISION.md`). Distributing a package with no license grants users no rights.
2. **PyPI Trusted-Publishing gate.** Publishing to PyPI without a long-lived token requires a human to
   configure a **pending publisher** on PyPI (project name, owner, repo, workflow filename,
   environment) before the first upload. This cannot be done from the repository.
3. **Governance gate (repository-internal).** The repository's own security tests
   (`tests/test_workflow_security.py`, `tests/test_m3f_inventories.py`) assert that **no** workflow may
   grant `contents: write`, request an **`id-token`** permission, reference a **secret**, or upload an
   artifact — and that every workflow references only the `astral.sh` host with SHA-pinned actions.
   PyPI Trusted Publishing needs `permissions: id-token: write` and the `pypa/gh-action-pypi-publish`
   action, both of which the current invariant forbids. Activating a live publish workflow therefore
   requires a **reviewed relaxation of that invariant** — a deliberate governance decision, not an
   automated edit.

Because of gate 3, the OIDC publish workflow below is shipped as a **template**, not as a live
`.github/workflows/*.yml`. The dry-run workflow, which needs none of those permissions, ships live.

## What ships live: `release-dry-run.yml` (read-only)

A `contents: read` workflow that builds the wheel + sdist on the authoritative runtime, runs the
private-data distribution scanner, computes SHA-256 checksums, generates an SBOM, and proves the
double build is byte-identical — and **uploads nothing, publishes nothing, needs no secret or
id-token**. This is the maximum publication-adjacent automation compatible with the governance
invariant, and it continuously proves the release is buildable and clean.

## Template (NOT active): OIDC Trusted-Publishing workflow

Activate this only after gates 1–3 are cleared. It is intentionally **not** under
`.github/workflows/` so it cannot run — and cannot violate the tested invariant — until a maintainer
chooses to enable it and adjusts the security test to permit exactly this one workflow.

```yaml
# .github/workflows/publish-release.yml  — TEMPLATE, do not enable without clearing gates 1-3
name: Publish release
on:
  push:
    tags: ["v[0-9]+.[0-9]+.[0-9]+"]
permissions:
  contents: read
  id-token: write            # OIDC for PyPI Trusted Publishing (forbidden by current governance test)
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683   # v4.2.2 (SHA-pinned)
      - name: Install uv (hash-pinned wheel)
        run: |
          python3 -m venv "$RUNNER_TEMP/uvenv"
          "$RUNNER_TEMP/uvenv/bin/python" -m pip install --require-hashes --only-binary=:all: -r ci/uv-requirements.txt
          echo "$RUNNER_TEMP/uvenv/bin" >> "$GITHUB_PATH"
      - name: Build
        run: uv build
      - name: Scan distribution (must be private-data-safe)
        run: uv run --no-sync python tools/scan_distribution.py dist/*.whl dist/*.tar.gz
      - name: Publish to PyPI via Trusted Publishing
        uses: pypa/gh-action-pypi-publish@<PIN-TO-40-HEX-SHA>   # requires a reviewed pin
        # No password/token: OIDC only. Requires a PyPI pending publisher configured for this repo.
```

## Maintainer runbook to actually publish

1. Clear gate 1 — add a `LICENSE` and declare it in `pyproject.toml` (`docs/V1_LICENSE_DECISION.md`).
2. Clear gate 2 — create the PyPI project + pending publisher bound to this repo and
   `publish-release.yml`.
3. Clear gate 3 — copy the template to `.github/workflows/publish-release.yml`, pin
   `pypa/gh-action-pypi-publish` to a reviewed 40-hex SHA, and update `tests/test_workflow_security.py`
   to allow `id-token: write` **only** for that one workflow (with a comment justifying it).
4. Push the annotated `v1.1.0` tag → the workflow builds, scans, and publishes via OIDC.
5. Verify with `pip install eth-research==1.1.0` in a clean environment (`docs/REPRODUCIBILITY.md`).

Until all three are cleared, `release_state.json` records the release as **built and hardened but not
published**, which is the honest terminal state of this program.
