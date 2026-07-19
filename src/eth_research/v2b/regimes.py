"""V2B §19 — causal market-regime tagging and per-regime paired diagnostics.

A regime label at bar ``t`` is decided **only** from information knowable strictly before the
target is acted on at ``open[t]`` — here, from BTC closes up to and including ``t-1``. So the regime
tag can never leak the same-bar move it is used to condition on. The single pre-registered regime
axis is the BTC trailing trend (BTC ``close[t-1]`` above or below its lagged simple moving average);
bars without a full lookback are tagged ``warmup`` and excluded from the per-regime diagnostic.

The per-regime paired mean log-excess return is **context only** — it shows whether a candidate's
edge (if any) concentrates in one regime — and is never itself a nomination gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eth_research.m3c.statistics import paired_log_excess
from eth_research.v2.strict import V2ValidationError

REGIMES_SCHEMA_VERSION: int = 1
#: The pre-registered BTC-trend lookback (bars) used to label the causal regime.
BTC_TREND_LOOKBACK: int = 200

REGIME_UPTREND = "btc_uptrend"
REGIME_DOWNTREND = "btc_downtrend"
REGIME_WARMUP = "warmup"
REGIME_LABELS = (REGIME_UPTREND, REGIME_DOWNTREND)


class V2BRegimeError(V2ValidationError):
    """A regime tagging or per-regime diagnostic invariant failed."""


def causal_btc_trend_regime(
    panel: pd.DataFrame, *, lookback: int = BTC_TREND_LOOKBACK
) -> pd.Series:
    """Label each bar by the causal BTC trend: ``close[t-1]`` vs its SMA over ``[t-lookback, t-1]``.

    Every input to the label at ``t`` is lagged one bar, so the regime is knowable before the
    target is acted on at ``open[t]``. The leading ``lookback`` bars (no window) are ``warmup``.
    """
    if "btc_close" not in panel.columns:
        raise V2BRegimeError("panel is missing btc_close")
    if lookback < 1:
        raise V2BRegimeError("lookback must be positive")
    btc = pd.Series(panel["btc_close"].to_numpy(dtype=float), index=panel.index)
    lagged = btc.shift(1)  # close[t-1]
    sma = lagged.rolling(lookback).mean()  # SMA over closes [t-lookback, t-1]
    labels = pd.Series(REGIME_WARMUP, index=panel.index, dtype=object)
    valid = lagged.notna() & sma.notna()
    labels[valid & (lagged > sma)] = REGIME_UPTREND
    labels[valid & (lagged <= sma)] = REGIME_DOWNTREND
    return labels


def regime_paired_means(
    candidate_net: pd.Series, benchmark_net: pd.Series, regime: pd.Series
) -> dict[str, dict[str, float]]:
    """Per-regime mean paired log-excess (candidate vs benchmark) over aligned, non-warmup bars.

    All three series must share the exact index. For each non-``warmup`` regime present, the mean
    daily paired log-excess and the observation count are reported (context only).
    """
    if not candidate_net.index.equals(benchmark_net.index) or not candidate_net.index.equals(
        regime.index
    ):
        raise V2BRegimeError("candidate, benchmark, and regime indices differ")
    out: dict[str, dict[str, float]] = {}
    for label in REGIME_LABELS:
        mask = (regime == label).to_numpy()
        if not mask.any():
            continue
        cand = candidate_net.to_numpy(dtype=float)[mask]
        bench = benchmark_net.to_numpy(dtype=float)[mask]
        excess = paired_log_excess(cand, bench)
        out[label] = {
            "observation_count": float(excess.size),
            "mean_paired_log_excess": float(np.mean(excess)),
        }
    return out
