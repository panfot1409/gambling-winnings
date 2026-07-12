# Earliest-continuous-series decision (Coinbase Exchange ETH-USD daily)

This records the explicit, evidence-based choice of the frozen dataset's start, machine-verified from the raw discovery response. No candle was ever filled, interpolated, resampled, or synthesized; a start is chosen, never a repair.

## Stage-A discovery evidence (re-derived from the raw bytes)

- Attempt `discovery-001`, workflow run `29180702904`, source commit `a86a8c3b9c7ede41989b1974e4a79c9895b3f7ef`.
- Discovery request window: [2016-05-01, 2017-02-01) (one request), retrieved 2026-07-12T05:07:28+00:00.
- Raw response SHA-256: `d13f1f4df537d6002ab0f7bea7fc8a74fe00317921d7a85406106375335380df`.
- Parsed candles in the window: **257**. First available daily candle: **2016-05-18**. Last candle in the discovery window: 2017-01-31.
- Absent early daily candles: **2016-05-21, 2016-05-22** (no trades/ticks published). The series is contiguous after the chosen start through the discovery window.

## Decision

- **Rejected start candidates:** every day up to and including the last absent candle. Days before 2016-05-18 precede the first available candle; the isolated early candles are rejected because the absent 2016-05-21, 2016-05-22 gap immediately follows, so a dataset beginning there would not be gap-free. This gap lies wholly in the earliest listing era, so the start is advanced past it — it is not a mid/recent-history gap (which would abort instead).
- **Chosen start = 2016-05-23** — the first daily candle after the last early-history gap, from which the series is continuous in the discovery window.
- **Chosen end = 2026-07-12** — the exclusive upper bound fixed in the committed acquisition plan; the forming final-day candle is excluded and this bound is never replaced with "now" during replay.

Full-series daily continuity from the chosen start onward is proven by the Stage-B acquisition and offline replay; a gap anywhere after the early era aborts the freeze with the offending timestamp — it is never filled.
