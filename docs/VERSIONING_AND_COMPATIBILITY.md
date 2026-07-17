# Versioning and compatibility

## Two version numbers

The project carries two distinct versions:

- **Package version** — the release version of the `eth-research` distribution,
  following [Semantic Versioning](https://semver.org/). This release pins
  `1.0.0`.
- **API version** (`API_VERSION`) — the version of the **public surface**
  (`eth_research.api.__all__` and the CLI), independent of the package version.
  This release is `"1.0"`. It is bumped only on a breaking change to the public
  surface, so an ordinary package release does not perturb it.

```bash
eth-research version
# eth-research 1.0.0 (public API 1.0)
```

## What the compatibility policy covers

The public contract is exactly:

- the names re-exported from `eth_research.api` (its `__all__`);
- the `eth-research` CLI commands, options, and exit codes;
- the on-disk schemas (result, receipt, manifest, config, validation report),
  each carrying an explicit integer schema version.

Everything else under `eth_research` — every non-exported module, including the
`eth_research.api.*` submodules, the engines, and the governance packages — is
an implementation detail and may change at any time without a version bump. Do
not import from it (see [MIGRATION_TO_V1.md](MIGRATION_TO_V1.md)).

## Schema versions

Each persisted artifact and the config embed an explicit integer schema version,
all `1` in this release: `result_schema_version`, `receipt_schema_version`,
`manifest_schema_version`, `config_schema_version`, and the validation report's
`schema_version`. A consumer should read and branch on these rather than
assuming a shape.

## Drift guards

Two deterministic snapshots pin the public surface so an accidental change is
caught in review. Each supports `--check` (verify) and `--write` (regenerate):

```bash
# public API surface — keyed by API_VERSION, so a package bump alone does not perturb it
python -m eth_research.m4a.public_api --check
python -m eth_research.m4a.public_api --write

# generated CLI reference — the concatenated --help of every command
python -m eth_research.m4a.cli_reference --check
python -m eth_research.m4a.cli_reference --write
```

The snapshots are stored under the governed `research/m4a/` tree
(`public_api.json` and `cli_reference.txt`) and are not shipped in the
distribution. `--check` fails closed when the committed snapshot no longer
matches the running package, so an accidental public-API or CLI change cannot
slip through unnoticed. The public-API snapshot is keyed by `API_VERSION`; the
CLI reference's rendered help depends on the exact CPython version's argparse
formatting, so its drift check is pinned to CPython 3.12 — skip it on another
interpreter.

## Deprecation policy

A public symbol is not removed abruptly. The policy is:

1. A symbol slated for removal is **deprecated for at least one minor release**
   while it keeps working, emitting a documented deprecation warning.
2. It is removed only in a subsequent **major** release, at which point
   `API_VERSION` is bumped for the breaking change.

Additive changes (new public names, new optional fields, new CLI options with
safe defaults) are minor and do not deprecate anything. New error kinds are
additive and never rename or repurpose an existing one — the error taxonomy is
closed and stable (see [PUBLIC_API.md](PUBLIC_API.md)).

## Practical guidance for consumers

- Import only from `eth_research.api`.
- Read `API_VERSION` and the per-artifact schema versions; branch on them.
- Treat exit codes as stable (0 success; 2 usage; 3–9 by error category; 70
  internal error).
- Do not depend on the exact text of a human-readable message; branch on an
  error's `code` or the CLI `--json` envelope instead.
