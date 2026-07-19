"""V2B §24 — a multi-asset (ETH/BTC/cash) offline vector-shadow extension.

The accepted shadow platform is signal-only and single-instrument: a :class:`SignalEnvelope` is one
candidate's long-only target weight for one instrument, valid as-of an instant, and the platform
never connects to a network, places an order, holds a credential, or moves money. V2B extends it to
the **joint** ETH/BTC/cash universe: each bar's target is a *vector* of two long-only envelopes
(ETH and BTC; cash ``= 1 - w_eth - w_btc``), re-asserting non-negativity and ``gross <= 1`` per bar.
Nothing here trades, prices, or reaches a network — it only records the multi-asset signal a live
operator would have *seen*, one causal bar late (a close-``<=t`` signal is as-of ``open[t+1]``).

A committed policy artifact (``research/v2b/multi_asset_shadow.json``) freezes the instruments, the
three non-live modes, the prohibitions, and the candidate ids; the per-bar vector machinery is
exercised on synthetic panels (never a committed real-partition performance artifact — the shadow
carries signals, not returns).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.shadow.domain import InstrumentId as ShadowInstrumentId
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, canonical_sha256
from eth_research.v2b.candidates import V2B_CANDIDATES, WEIGHT_BTC, WEIGHT_ETH, V2BCandidateSpec
from eth_research.v2b.evaluation import candidate_execution_path

SHADOW_SCHEMA_VERSION: int = 1
MULTI_ASSET_SHADOW_RELPATH: str = "research/v2b/multi_asset_shadow.json"

ETH_INSTRUMENT: ShadowInstrumentId = ShadowInstrumentId(symbol="eth_usd")
BTC_INSTRUMENT: ShadowInstrumentId = ShadowInstrumentId(symbol="btc_usd")
#: The three non-live shadow modes — no live/connected mode exists.
SHADOW_MODES: tuple[str, ...] = ("synthetic_demo", "historical_shadow", "paper_simulation")
#: The fail-closed prohibitions the shadow platform enforces (re-asserted for the vector extension).
PROHIBITIONS: tuple[str, ...] = (
    "no_network",
    "no_orders",
    "no_credentials",
    "no_money_movement",
    "no_leverage_or_shorting",
)
_GROSS_TOLERANCE: float = 1e-9


class V2BShadowError(V2ValidationError):
    """A multi-asset shadow vector violated the long-only gross<=1 signal-only contract."""


@dataclass(frozen=True, slots=True)
class MultiAssetSignalVector:
    """One bar's ETH/BTC/cash target as a vector of two long-only signal envelopes plus cash."""

    as_of: str
    eth: SignalEnvelope
    btc: SignalEnvelope
    cash_weight: float

    def to_canonical(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "eth": self.eth.to_canonical(),
            "btc": self.btc.to_canonical(),
            "cash_weight": self.cash_weight,
        }


def _vector(candidate_id: str, as_of: str, w_eth: float, w_btc: float) -> MultiAssetSignalVector:
    gross = w_eth + w_btc
    if w_eth < 0.0 or w_btc < 0.0:
        raise V2BShadowError("shadow vector has a negative weight (no shorting)")
    if gross > 1.0 + _GROSS_TOLERANCE:
        raise V2BShadowError(f"shadow vector gross {gross!r} exceeds 1 (no leverage)")
    return MultiAssetSignalVector(
        as_of=as_of,
        eth=SignalEnvelope.create(
            candidate_id=candidate_id, instrument=ETH_INSTRUMENT, as_of=as_of, target_weight=w_eth
        ),
        btc=SignalEnvelope.create(
            candidate_id=candidate_id, instrument=BTC_INSTRUMENT, as_of=as_of, target_weight=w_btc
        ),
        cash_weight=max(0.0, 1.0 - gross),
    )


def build_shadow_vectors(
    spec: V2BCandidateSpec, panel: pd.DataFrame
) -> tuple[MultiAssetSignalVector, ...]:
    """The candidate's causal executed path as a per-bar ETH/BTC/cash signal-vector timeline.

    The target acted on at ``open[t]`` is the signal decided from closes strictly before it, so each
    vector is ``as_of`` the bar's open. Signal-only: no returns, prices, orders, or connectivity.
    """
    executed = candidate_execution_path(spec, panel)
    w_eth = executed[WEIGHT_ETH].to_numpy(dtype=float)
    w_btc = executed[WEIGHT_BTC].to_numpy(dtype=float)
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    vectors: list[MultiAssetSignalVector] = []
    for i, ts in enumerate(index):
        as_of = pd.Timestamp(ts).isoformat().replace("+00:00", "Z")
        vectors.append(_vector(spec.candidate_id, as_of, float(w_eth[i]), float(w_btc[i])))
    return tuple(vectors)


@dataclass(frozen=True, slots=True)
class ShadowSummary:
    """A signal-only summary of one candidate's multi-asset shadow timeline (no performance)."""

    candidate_id: str
    bar_count: int
    eth_active_bars: int
    btc_active_bars: int
    cash_bars: int
    leg_transitions: int  # bars whose active-leg differs from the previous bar

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "bar_count": self.bar_count,
            "eth_active_bars": self.eth_active_bars,
            "btc_active_bars": self.btc_active_bars,
            "cash_bars": self.cash_bars,
            "leg_transitions": self.leg_transitions,
        }


def build_shadow_summary(spec: V2BCandidateSpec, panel: pd.DataFrame) -> ShadowSummary:
    """Reduce a candidate's shadow vectors to signal-only counts (legs, cash, transitions)."""
    vectors = build_shadow_vectors(spec, panel)

    def leg(v: MultiAssetSignalVector) -> str:
        if v.eth.target_weight > 0.0:
            return "eth"
        if v.btc.target_weight > 0.0:
            return "btc"
        return "cash"

    legs = [leg(v) for v in vectors]
    transitions = sum(1 for a, b in pairwise(legs) if a != b)
    return ShadowSummary(
        candidate_id=spec.candidate_id,
        bar_count=len(vectors),
        eth_active_bars=legs.count("eth"),
        btc_active_bars=legs.count("btc"),
        cash_bars=legs.count("cash"),
        leg_transitions=transitions,
    )


# --------------------------------------------------------------------------- #
# committed policy artifact (deterministic; no real-partition signals)          #
# --------------------------------------------------------------------------- #
def build_shadow_policy() -> dict[str, Any]:
    """The frozen multi-asset shadow policy: instruments, modes, prohibitions, candidate ids."""
    policy = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "kind": "v2b_multi_asset_shadow_policy",
        "base_currency": "USD",
        "instruments": [ETH_INSTRUMENT.symbol, BTC_INSTRUMENT.symbol],
        "modes": list(SHADOW_MODES),
        "prohibitions": list(PROHIBITIONS),
        "candidate_ids": [spec.candidate_id for spec in V2B_CANDIDATES],
        "signal_only": True,
        "gross_leq_one": True,
        "causal_lag_bars": 1,
    }
    policy["policy_fingerprint"] = canonical_sha256(policy)
    return policy


def render_shadow_policy_bytes() -> bytes:
    return canonical_json_bytes(build_shadow_policy())


def verify_shadow_policy(repo_root: str | Path) -> None:
    committed = (Path(repo_root) / MULTI_ASSET_SHADOW_RELPATH).read_bytes()
    if committed != render_shadow_policy_bytes():
        raise V2BShadowError("committed multi_asset_shadow.json does not reproduce")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B multi-asset shadow policy (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / MULTI_ASSET_SHADOW_RELPATH
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_shadow_policy_bytes())
        print(f"wrote {MULTI_ASSET_SHADOW_RELPATH}")
        return 0
    try:
        verify_shadow_policy(args.repo_root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
