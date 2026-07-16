# research/m4a — Milestone 4A release-candidate artifacts

Deterministic, source-derived artifacts that pin the v1.0.0 public surface. They are
committed for review and drift detection; they are **not** shipped in the distribution.

- `public_api.json` — a canonical snapshot of the public API surface
  (`eth_research.api.__all__`), keyed by `API_VERSION`. Regenerate with
  `python -m eth_research.m4a.public_api --write`; verify with `--check`.
- `cli_reference.txt` — the generated `eth-research` CLI reference (the concatenated
  `--help` of every command). Regenerate with
  `python -m eth_research.m4a.cli_reference --write`; verify with `--check`. Its
  rendered help depends on the exact CPython argparse formatting, so the drift check is
  pinned to CPython 3.12.

The four release-candidate artifacts below are deterministic, source-derived records — no
binary is committed. Regenerate all four with `python -m eth_research.m4a.release --write`;
verify with `--check`.

- `distribution_manifest.json` — the pure-Python members that ship inside the package
  (`.py` / `.pyi` + `py.typed`), each with its content hash. `tests/test_m4a_release.py`
  builds the wheel and proves the built distribution ships exactly these members, byte for
  byte.
- `distribution_dependencies.json` — the pinned runtime dependency graph (the offline
  `numpy` / `pandas` / `pyarrow` stack) with the versions locked in `uv.lock` and the pinned
  build backend.
- `release_candidate_state.json` — the frozen RC state: package/API versions, every artifact
  schema version, and the sha256 of each of the three sealed governance ledgers (each must be
  the empty-string digest) plus the public-API and CLI-reference snapshots.
- `distribution_proof.json` — an attestation of the proofs that back the distribution (double
  build byte-identity, scanner-clean, consumer E2E, offline import closure), each naming the
  test that establishes it.

Every `--check` guard fails closed when a committed artifact no longer matches the running
package, so an accidental public-API, CLI, distribution, or governance-state change is caught
in review. This is a governed root: it self-verifies here and is out of scope for the accepted
M2B–M3E stack freeze table and the frozen M3F audit.
