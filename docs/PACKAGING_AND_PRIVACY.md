# Packaging and privacy

The distribution is designed to ship the runtime package and nothing else. The
research repository contains raw market data and sealed governance ledgers that
must never leave it; packaging is therefore built around a strict allowlist and
verified by a scanner on the built artifacts.

## What the distribution contains

Both the wheel and the source distribution ship only:

- the runtime package source, `eth_research/` (including `py.typed`);
- the build metadata (`pyproject.toml`, and `README.md` in the sdist);
- the standard generated metadata (`.dist-info` / `PKG-INFO`).

The wheel is pure Python, tagged `py3-none-any`, and declares the single
`eth-research` console entry point. There are no compiled extensions.

## What is never packaged

The sdist uses a strict `only-include` allowlist (an anchored path list), so
everything else is excluded by omission rather than by trying to enumerate what
to drop. The following are never included in either artifact:

- the governed `research/` tree — raw market data and the sealed ledgers;
- `tests/`, `tools/`, `docs/`, and `.github/`;
- the lockfile, dotfiles, and byte-compiled caches.

## The distribution scanner

`tools/scan_distribution.py` is a supply-chain integrity gate. It opens a built
`.whl` or `.tar.gz` and fails closed unless every member is on the allowlist and
the artifact is a clean pure-Python distribution. It checks, among other things,
that:

- every path is relative and traversal-free (no absolute path, no `..`);
- no member is a symlink or hardlink;
- no path segment names a private or governance root (`research`, `.git`,
  `.github`, `tests`, `tools`, `docs`, `__pycache__`, `.env`);
- no member carries a data, secret, or binary extension (`.parquet`, `.csv`,
  `.jsonl`, `.env`, `.pem`, `.key`, `.so`, `.pyd`, `.dll`, …);
- **inside the package tree** the allowlist is inverted to admit only pure-Python
  files — `.py` / `.pyi` sources and the `py.typed` marker — so a data file of
  *any* extension (a raw candle `.json`, a manifest, a pickle) dropped under
  `eth_research/` is rejected, not merely the few denied suffixes above;
- the wheel ships `eth_research/py.typed`, declares the console entry point, and
  is tagged `py3-none-any`.

Run it on the build outputs:

```bash
uv build
python tools/scan_distribution.py dist/eth_research-1.0.0-py3-none-any.whl dist/eth_research-1.0.0.tar.gz
```

A clean artifact prints `<path>: clean`; any violation is reported and exits
non-zero. This verifies the inclusion allowlist held — a raw market-data byte or
a sealed ledger can never be shipped — but it is an integrity gate, not a proof
of provenance.

## Reproducible build

The build is reproducible: building the wheel and sdist twice from the same
source produces byte-identical artifacts (the "double build" is byte-identical).
This lets a reviewer rebuild independently and confirm the artifacts match.

## No license yet — not cleared for public upload

> The repository ships **no `LICENSE` file**. Without a license the distribution
> is **not cleared for public or PyPI upload**. This is a known, deliberate
> limitation of the v1.0.0 release candidate, not an oversight to be worked
> around by inventing a license. Build and install locally only. See
> [V1_LIMITATIONS.md](V1_LIMITATIONS.md).

## Reproducibility of the surface

The public API snapshot and the generated CLI reference are governed artifacts
that live under `research/m4a/` (and are therefore not shipped in the
distribution). They exist to catch accidental drift in the public surface; see
[VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md).
