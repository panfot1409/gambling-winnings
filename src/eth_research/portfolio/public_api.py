"""The additive M4B (v1.1) public-API snapshot and its additivity guard (Milestone 4B, §28).

The M4B public surface is *additive* over the accepted M4A v1.0 API: every v1.0 name keeps its exact
descriptor, and the portfolio milestone only adds new value models and pure functions on top. This
module snapshots both layers — the running :data:`eth_research.api.__all__` (v1.0) and the new M4B
symbols — into ``research/m4b/public_api.json``, keyed by the public-contract ``M4B_API_VERSION``.

Two guards protect the contract. :func:`verify` fails closed when the committed v1.1 snapshot no
longer matches the running package (an accidental M4B public-API change cannot slip through review).
:func:`verify_additive` fails closed when the v1.0 layer of the running snapshot no longer byte-
matches M4A's committed ``research/m4a/public_api.json`` — proving the v1.1 surface only *adds* to
v1.0 and never mutates it. The M4A snapshot is read, never written, here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from eth_research import api
from eth_research.api.serialization import canonical_json_bytes, strict_load_canonical
from eth_research.m4a.public_api import SNAPSHOT_RELPATH as M4A_SNAPSHOT_RELPATH
from eth_research.m4a.public_api import _describe
from eth_research.portfolio import M4B_PACKAGE_VERSION
from eth_research.portfolio.bars import validate_bar_frame
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateAction, CorporateActionSet
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence, FxObservation
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.metrics import PortfolioMetrics, compute_portfolio_metrics
from eth_research.portfolio.panel import MarketPanel, build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.reference import build_reference_universe, reference_protocol
from eth_research.portfolio.result import (
    PortfolioResult,
    build_portfolio_result,
    verify_portfolio_result,
)
from eth_research.portfolio.streaming import (
    PortfolioCheckpoint,
    resume_portfolio_simulation,
    stream_portfolio_simulation,
)
from eth_research.portfolio.targets import PortfolioTarget
from eth_research.portfolio.trace import (
    TraceCommitment,
    build_trace_commitment,
    verify_trace_commitment,
)
from eth_research.portfolio.universe import UniverseSpec

__all__ = [
    "M4A_SNAPSHOT_RELPATH",
    "M4B_API_VERSION",
    "SNAPSHOT_RELPATH",
    "PublicAPIDriftError",
    "build_snapshot",
    "main",
    "snapshot_bytes",
    "verify",
    "verify_additive",
]

M4B_API_VERSION = "1.1"
SNAPSHOT_RELPATH = "research/m4b/public_api.json"
SNAPSHOT_SCHEMA_VERSION = 1

#: The additive M4B public surface, name -> object. Existing v1.0 names are not repeated here; they
#: are snapshotted from :data:`eth_research.api.__all__`.
_M4B_SYMBOLS: dict[str, object] = {
    "CorporateAction": CorporateAction,
    "CorporateActionSet": CorporateActionSet,
    "FxEvidence": FxEvidence,
    "FxObservation": FxObservation,
    "InstrumentId": InstrumentId,
    "M4B_PACKAGE_VERSION": M4B_PACKAGE_VERSION,
    "MarketPanel": MarketPanel,
    "MembershipInterval": MembershipInterval,
    "MembershipSchedule": MembershipSchedule,
    "PortfolioCheckpoint": PortfolioCheckpoint,
    "PortfolioMetrics": PortfolioMetrics,
    "PortfolioProtocol": PortfolioProtocol,
    "PortfolioResult": PortfolioResult,
    "PortfolioTarget": PortfolioTarget,
    "TraceCommitment": TraceCommitment,
    "TradingCalendar": TradingCalendar,
    "UniverseSpec": UniverseSpec,
    "build_market_panel": build_market_panel,
    "build_portfolio_result": build_portfolio_result,
    "build_reference_universe": build_reference_universe,
    "build_trace_commitment": build_trace_commitment,
    "compute_portfolio_metrics": compute_portfolio_metrics,
    "reference_protocol": reference_protocol,
    "resume_portfolio_simulation": resume_portfolio_simulation,
    "run_portfolio_simulation": run_portfolio_simulation,
    "stream_portfolio_simulation": stream_portfolio_simulation,
    "validate_bar_frame": validate_bar_frame,
    "verify_portfolio_result": verify_portfolio_result,
    "verify_trace_commitment": verify_trace_commitment,
}


class PublicAPIDriftError(RuntimeError):
    """The committed M4B public-API snapshot no longer matches the running package."""


def _v1_0_symbols() -> dict[str, Any]:
    return {name: _describe(getattr(api, name)) for name in sorted(api.__all__)}


def build_snapshot() -> dict[str, Any]:
    """Build the canonical additive v1.1 public-API snapshot for the running package."""
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "api_version": M4B_API_VERSION,
        "base_api_version": api.API_VERSION,
        "v1_0_symbols": _v1_0_symbols(),
        "m4b_symbols": {name: _describe(obj) for name, obj in sorted(_M4B_SYMBOLS.items())},
    }


def snapshot_bytes() -> bytes:
    return canonical_json_bytes(build_snapshot())


def verify_additive(repo_root: str | Path) -> None:
    """Fail closed unless the v1.0 layer still byte-matches M4A's committed snapshot (additive)."""
    path = Path(repo_root) / M4A_SNAPSHOT_RELPATH
    try:
        committed = strict_load_canonical(path.read_bytes(), "m4a_public_api")
    except OSError as exc:
        raise PublicAPIDriftError(f"M4A snapshot missing at {M4A_SNAPSHOT_RELPATH}: {exc}") from exc
    if not isinstance(committed, dict) or "symbols" not in committed:
        raise PublicAPIDriftError("M4A snapshot is malformed")
    # Compare via canonical JSON bytes so a tuple-vs-list (constant tuples reload from JSON as
    # lists) is not a false positive; only a genuine descriptor change trips the guard.
    if canonical_json_bytes(_v1_0_symbols()) != canonical_json_bytes(committed["symbols"]):
        raise PublicAPIDriftError(
            "the v1.1 API is not additive: a v1.0 symbol changed relative to research/m4a/"
            "public_api.json"
        )


def verify(repo_root: str | Path) -> None:
    """Fail closed unless the committed v1.1 snapshot matches the package (and stays additive)."""
    verify_additive(repo_root)
    path = Path(repo_root) / SNAPSHOT_RELPATH
    try:
        committed = path.read_bytes()
    except OSError as exc:
        raise PublicAPIDriftError(f"v1.1 snapshot missing at {SNAPSHOT_RELPATH}: {exc}") from exc
    fresh = snapshot_bytes()
    if committed != fresh:
        recanonical = canonical_json_bytes(strict_load_canonical(committed, "m4b_public_api"))
        if recanonical != fresh:
            raise PublicAPIDriftError(
                "the public API changed but research/m4b/public_api.json was not regenerated"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4B public-API snapshot: --check or --write.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed snapshot")
    group.add_argument("--write", action="store_true", help="(re)write the committed snapshot")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / SNAPSHOT_RELPATH
    if args.write:
        verify_additive(args.repo_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot_bytes())
        sys.stdout.write(f"wrote {SNAPSHOT_RELPATH}\n")
        return 0
    try:
        verify(args.repo_root)
    except PublicAPIDriftError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("M4B public API snapshot is current and additive over v1.0\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
