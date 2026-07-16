# M3D Prospective Protocol

The pre-registered protocol for the future-only prospective ETH-USD daily cohort.
It is **data-only**: the protocol governs acquisition, freezing, and maturity — it
authorizes **no** evaluation. The machine-readable form is
`research/m3d/prospective_protocol.json`; this document is its prose companion.

## Purpose

The research-train partition is treated as exhausted for new candidate research
(see `docs/M3D_RESEARCH_TRAIN_EXHAUSTION.md`). To enable any *future* out-of-sample
review without contaminating the exhausted training data, M3D establishes a
strictly non-overlapping prospective cohort of data that did not exist when the
research program was designed.

## Boundaries

- **Source:** public Coinbase Exchange candles endpoint
  `https://api.exchange.coinbase.com/products/ETH-USD/candles`, unauthenticated,
  1-day granularity, candle-open UTC timestamps.
- **Cohort start (fixed):** `2026-07-12T00:00:00Z` — strictly after the final M2B
  candle open (`2026-07-11T00:00:00+00:00`). No prospective candle may fall at or
  before the final M2B candle; overlap is a HARD STOP.
- **Overall end:** the first UTC midnight after the most recent fully completed
  day, computed from an explicit `as_of` (never a wall clock) so the window covers
  only completed days and never a forming candle.
- **Timestamp / transformation convention:** Coinbase returns
  `[time, low, high, open, close, volume]` newest-first; the transformation maps to
  canonical `(timestamp, open, high, low, close, volume)`, reversing only a strictly
  descending response and rejecting any other ordering. Request `start`/`end` are
  inclusive bucket opens (`start = window_start`, `end = window_end - 1 day`); the
  parse window is half-open `[window_start, window_end)`.

## Maturity rule (hard)

A cohort is **mature** only when ALL of the following hold, assessed from committed
evidence alone:

1. at least **365** completed daily observations;
2. it begins exactly at the fixed cohort start;
3. a continuous daily cadence with no gap, duplicate, or reorder;
4. zero structural quality errors;
5. an independent reacquisition reproduces the canonical content exactly.

Nominal maturity is reached no earlier than the `2027-07-11` open (365 daily
candles from `2026-07-12`). At freeze the cohort holds **3** observations and is
therefore **immature**.

## Maturity is necessary, never sufficient

Even a mature cohort is **not** evaluation-authorized. M3D contains no evaluation
function and authorizes nothing; `evaluation_authorized` is false regardless of
maturity. The prospective evaluation ledger
(`research/m3d/prospective_evaluations.jsonl`) is created byte-empty and is never
appended in this milestone. Any future evaluation would be a separately reviewed,
separately pre-registered milestone — not an M3D capability.

## Independence and reproducibility

Two independent acquisitions (genesis + audit) over the identical request window
must produce byte-identical canonical content under distinct plan hashes, source
commits, and workflow runs. The whole facility re-derives byte-for-byte offline
from the committed raw bytes; there is no numerical tolerance because no strategy
or statistic exists to compare.
