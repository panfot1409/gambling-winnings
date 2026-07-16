# Reproducibility

The platform is built so that the same research inputs produce the same bytes,
on any machine, every time. This document explains the mechanisms that make a
run reproducible and what is (and is not) covered.

## Canonical serialization

Every committed artifact — result, receipt, config, manifest — is written in one
canonical JSON form: keys sorted, two-space indent, UTF-8 (no ASCII escaping),
`NaN`/`Infinity` refused at serialize time, and exactly one trailing newline.
Serialization is a fixed point: parsing a canonical artifact and re-serializing
it reproduces the same bytes. Every artifact therefore has a stable SHA-256.

Parsing is equally strict: duplicate keys, non-finite numbers, trailing data,
and non-UTF-8 are rejected, and no value is coerced (a `bool` is not an `int`, a
numeric string is not a number).

## Deterministic synthetic data

`generate_synthetic_dataset` takes no I/O and no clock. The same arguments always
produce the same OHLCV bytes, so any example or test built on synthetic data is
fully reproducible.

## Deterministic results

A `ResearchResult` is the immutable record of one run. Because the engines are
deterministic and the serialization is canonical, re-running identical inputs
yields byte-identical result bytes and an identical `result_sha256`:

```python
from eth_research.api import (
    generate_synthetic_dataset, run_binary_backtest, StrategySpec, CostSpec,
)

d = generate_synthetic_dataset(n_periods=400, seed=0)
a = run_binary_backtest(d, StrategySpec("buy_and_hold"), CostSpec("base"))
b = run_binary_backtest(d, StrategySpec("buy_and_hold"), CostSpec("base"))
assert a.to_json_bytes() == b.to_json_bytes()
assert a.result_sha256 == b.result_sha256
```

## Machine-independent run id

Each run has a deterministic `run_id`: the SHA-256 of the immutable research
inputs alone (engine, dataset fingerprint, strategy identity and fixed
parameters, cost scenario, initial cash, context bars, risk-free rate). Because
it is derived from the research inputs and nothing about the host, the same study
produces the same `run_id` on any machine.

Environment facts — the Python implementation and version and the
numpy/pandas/pyarrow versions — are **recorded** in the receipt as facts, but
they are not part of the `run_id` and are not re-checked against the verifying
machine. So a receipt from one machine verifies on another as long as the bound
artifact bytes match.

## Run receipts

`build_receipt` binds the SHA-256 of the exact result (and optionally report,
config, and dataset manifest) bytes it is given. `verify_run_receipt` re-checks
those digests, confirms the recorded research identity matches the result, and
recomputes the `run_id` from the receipt's own fields. Any mismatch raises
`ReceiptVerificationError`. See
[RESULT_AND_RECEIPT_SCHEMAS.md](RESULT_AND_RECEIPT_SCHEMAS.md).

## Transactional output

`backtest run` publishes its bundle transactionally: every file's bytes are
computed up front, each is written atomically and read back and byte-verified,
and `manifest.json` is written last as the completeness marker. On any failure
the whole bundle is rolled back, leaving no partial or temporary residue. A
bundle that exists is therefore always complete and internally consistent.

## Reproducible distribution build

The wheel and sdist build reproducibly: building twice from the same source
produces byte-identical artifacts. See
[PACKAGING_AND_PRIVACY.md](PACKAGING_AND_PRIVACY.md).

## Public-surface drift guards

Two deterministic snapshots pin the public contract so an accidental change is
caught in review:

```bash
python -m eth_research.m4a.public_api --check      # public API surface
python -m eth_research.m4a.cli_reference --check    # generated CLI reference
```

Regenerate them intentionally with `--write` when the surface changes on
purpose. The CLI reference's rendered `--help` text depends on the exact CPython
version's argparse formatting, so its drift check is pinned to CPython 3.12;
skip it on another interpreter. See
[VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md).

## Scope of the guarantee

Determinism holds for a fixed dependency stack on a given platform. Byte-for-byte
identity of results and builds **across operating systems** (for example between
Linux, macOS, and Windows) is only claimed where it has been demonstrated; it is
not asserted here as a blanket guarantee. See
[V1_LIMITATIONS.md](V1_LIMITATIONS.md).
