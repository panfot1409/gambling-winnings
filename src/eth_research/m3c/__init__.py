"""Milestone 3C — adaptive research governance + one preregistered experiment.

M3C evaluates exactly one new, fixed, preregistered long-only candidate
(``dual_horizon_trend_63_252_vol_target_30d_50pct``) on the existing research-train
partition only, against fixed benchmarks, with fold-seam-aware paired bootstrap
inference and a mechanical promotion-eligibility decision. It never accesses the
development gate or final holdout, evaluates no second candidate, changes no
parameter after seeing results, and modifies no M2B/M3A/M3B immutable artifact.

The financial engine, accounting, solver, liquidity, cost model, risk overlays,
metrics, and reconciliation are the reviewed Milestone 3B implementations, reused
unmodified. This package adds only the governance/provenance layer and the one new
candidate signal.
"""

from __future__ import annotations

M3C_MILESTONE: str = "M3C"
M3C_PACKAGE_VERSION: str = "0.6.0"
