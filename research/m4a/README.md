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

Both `--check` guards fail closed when the committed snapshot no longer matches the
running package, so an accidental public-API or CLI change is caught in review. This is a
governed root: it self-verifies here and is out of scope for the accepted M2B–M3E stack
freeze table and the frozen M3F audit.
