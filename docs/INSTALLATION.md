# Installation

`eth-research` is a research-only, offline Python platform. It is a pure-Python
package with no compiled extensions and no network client of any kind.

## Requirements

- Python 3.12 or newer (`requires-python >=3.12`).
- Runtime dependencies, installed automatically:
  - `numpy>=1.26`
  - `pandas>=2.2`
  - `pyarrow>=15`

No system libraries, no compiler, and no network access are required at runtime.

## Not yet on PyPI

There is intentionally **no** published PyPI release. The distribution is not
cleared for public upload because the repository ships no `LICENSE` file yet
(see [V1_LIMITATIONS.md](V1_LIMITATIONS.md)). The following command is therefore
the shape of a future release, and does **not** work today:

```bash
pip install eth-research   # not available: no PyPI release yet
```

Install from a locally built wheel instead.

## Install from a built wheel

Build the wheel and source distribution with [uv](https://docs.astral.sh/uv/)
(recommended — it uses the versions locked in `uv.lock`):

```bash
uv build
```

This writes two artifacts into `dist/`:

```
dist/eth_research-1.0.0-py3-none-any.whl
dist/eth_research-1.0.0.tar.gz
```

Install the wheel into any Python 3.12+ environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install dist/eth_research-1.0.0-py3-none-any.whl
```

The wheel is tagged `py3-none-any` (pure Python), so the same file installs on
any platform with a compatible interpreter.

## Development install

To work on the package itself, sync the locked runtime and development
toolchain (mypy, pytest, ruff):

```bash
uv sync --locked --all-extras
```

Or with pip, using floating versions within the `pyproject.toml` bounds:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Verify the installation

The package installs a single console entry point, `eth-research`. Confirm the
versions and run the built-in offline self-test:

```bash
eth-research version
eth-research doctor
```

`version` prints the package version and the public-API contract version.
`doctor` additionally reports the interpreter and dependency versions and runs a
short synthetic backtest to confirm the offline pipeline works end to end:

```
eth-research 1.0.0 (API 1.0)
python CPython 3.12.3
numpy 2.5.1  pandas 3.0.3  pyarrow 25.0.0
[ok] synthetic_pipeline
[ok] offline no network client is imported by the package
```

Exact dependency version numbers depend on what your environment resolved.

## Next steps

- [QUICKSTART.md](QUICKSTART.md) — run a backtest end to end, offline.
- [PUBLIC_API.md](PUBLIC_API.md) — the supported Python surface.
- [PACKAGING_AND_PRIVACY.md](PACKAGING_AND_PRIVACY.md) — what the distribution
  does and does not contain.
