# Earliest-continuous-series decision (Coinbase Exchange ETH-USD daily)

This records the explicit, evidence-based choice of `overall_start` and
`overall_end` for the frozen Milestone 2B dataset. No candle was ever
filled, interpolated, resampled, or synthesized; a start is chosen, never a
repair.

## Stage-A discovery evidence

- Workflow: `.github/workflows/m2b-acquire.yml`, run **29180702904**,
  attempt `discovery-001`, source commit
  `a86a8c3b9c7ede41989b1974e4a79c9895b3f7ef`.
- Discovery request window: `[2016-05-01, 2017-02-01)` (one request).
- Raw response: `research/m2b/raw/coinbase/discovery-001/coinbase-eth-usd-1d_0000_20160501_20170201.json`
  — HTTP 200, 12 900 bytes, SHA-256
  `d13f1f4df537d6002ab0f7bea7fc8a74fe00317921d7a85406106375335380df`,
  retrieved 2026-07-12T05:07:28Z.
- Parsed candles in the window: **257**. First available daily candle:
  **2016-05-18**. Last candle in the discovery window: 2017-01-31.
- Exactly one gap in the discovered range: **2016-05-20 → 2016-05-23**
  (the daily candles for **2016-05-21** and **2016-05-22** are absent from
  Coinbase — no trades/ticks published). The series is contiguous after
  2016-05-23 through the end of the discovery window.

## Decision

- **Rejected start candidates:** every day in `2016-05-01 .. 2016-05-22`.
  `2016-05-01 .. 2016-05-17` precede the first available candle; the
  isolated candles `2016-05-18/19/20` are rejected because they are
  immediately followed by the 2016-05-21/22 gap, so a dataset beginning
  there would not be gap-free. This gap lies wholly in the earliest listing
  era, so the start is advanced past it — it is **not** a mid/recent-history
  gap (which would abort instead).
- **Chosen `overall_start` = 2016-05-23** — the first daily candle after
  the last early-history gap, from which the series is continuous in the
  discovery window.
- **Chosen `overall_end` = 2026-07-12** — the first UTC midnight after the
  last fully completed daily candle (2026-07-11); the forming 2026-07-12
  candle is excluded. This bound is fixed in the committed plan and is never
  replaced with "now" during replay.

## Frozen request plan

`research/m2b/acquisition_request_plan.json` tiles `[2016-05-23,
2026-07-12)` into **13** contiguous ≤299-day windows (3 702 daily buckets),
plan SHA-256
`f8f77ddbd226287e3561cd169de0b4fada090d66bd6a09d70e045f6b786ebf83`.

Full-series daily continuity from 2016-05-23 through 2026-07-11 is proven
by the Stage-B acquisition + offline replay (`_check_daily_continuity`). A
gap anywhere after the early era aborts the freeze with the offending
timestamp — it is never filled.
