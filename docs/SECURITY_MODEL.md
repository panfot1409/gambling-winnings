# Security model

This is a research-only, offline platform. Its security posture follows from
that: it has no live-trading surface to attack, it reads and writes only what
the caller names, and it commits artifacts that contain no secrets. This
document states the trust boundaries explicitly.

## No live-trading surface

By design, the package contains **none** of the following:

- exchange connectivity or any network client;
- authentication, API keys, or credentials;
- wallet integration or key handling;
- order routing or execution against a venue;
- leverage, shorting, margin, or derivatives.

It operates only on historical OHLCV data from local files or the deterministic
synthetic generator. The `doctor` command asserts that no network client is
imported by the package. There is nothing here that can place an order, move
funds, or reach the network.

## Trust boundary: custom strategies

A built-in strategy is named by a `StrategySpec` and validated against a closed
enumeration — this is the only form the CLI and the config accept. The Python
API additionally accepts a **custom `Strategy` instance** you pass in directly.

> A custom strategy is **trusted caller code.** It runs in-process, is **not
> sandboxed**, and executing a backtest with it runs your code with your
> privileges. There is no plugin loader, no dynamic import from a path, and no
> `eval`/`exec` — a strategy is always a Python object you already hold and
> chose to run. Treat a strategy object from an untrusted source exactly as you
> would any untrusted Python code: do not run it.

See [CUSTOM_STRATEGIES.md](CUSTOM_STRATEGIES.md).

## Configuration path safety

The strict run-config parser fails closed and refuses dangerous paths. Every
filesystem path in a config must be a relative, traversal-free local path. A
path is rejected if it is absolute, contains `..`, is a URL, references the
governed `research/` roots, or names a `.git` directory. Relative paths resolve
against the config file's own directory, never the process working directory.
The parser also rejects unknown keys, string-to-number coercion, `bool` read as
`int`, and non-finite numbers.

## Output safety

The bundle publisher never clobbers by default and never escapes its target
directory:

- an existing output file is a collision unless `overwrite` is set;
- unsafe filenames, path separators, `..`, and symlinks are refused;
- each file is written atomically, read back, and byte-verified;
- on any failure the whole bundle is rolled back — no partial, temporary, or
  backup residue remains.

The CLI refuses to overwrite by default across all commands, never prompts,
never uses colour, and writes only inside the output directory it is told to
use.

## What a receipt does not record

A `RunReceipt` is safe to share. It binds versions, the immutable research
identity, and artifact digests, and it deliberately records **no** credential,
wallet, key, absolute path, hostname, username, IP address, wall-clock time,
environment dump, or command string. The recorded interpreter and dependency
versions are the only environment facts, and they are stated as facts, not
secrets. Error messages (which may mention a path for a human) go only to the
CLI's human or `--json` error output; they are never serialized into a result
or receipt.

## Error taxonomy and exit codes

Failures a caller can provoke map to a closed error taxonomy with stable exit
codes (3–9 by category; see [PUBLIC_API.md](PUBLIC_API.md)). A genuine bug is
deliberately **not** wrapped as a user error — it propagates as itself, and the
CLI reports it as an internal error with exit code 70, so a defect is never
silently reported as bad input.

## Private research data is never packaged

The governed `research/` tree — raw market data and sealed governance
ledgers — plus tests, tools, docs, and `.github` are never included in the wheel
or sdist. A distribution scanner enforces the allowlist on the built artifacts.
See [PACKAGING_AND_PRIVACY.md](PACKAGING_AND_PRIVACY.md).
