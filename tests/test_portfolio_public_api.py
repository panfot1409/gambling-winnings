"""The additive M4B (v1.1) public-API snapshot: currency, additivity, and drift guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research.api.serialization import canonical_json_bytes, strict_load_canonical
from eth_research.portfolio.public_api import (
    M4A_SNAPSHOT_RELPATH,
    SNAPSHOT_RELPATH,
    PublicAPIDriftError,
    build_snapshot,
    snapshot_bytes,
    verify,
    verify_additive,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_committed_snapshot_is_current_and_additive() -> None:
    # Fails if research/m4b/public_api.json is stale or the v1.0 layer drifted from M4A's snapshot.
    verify(_REPO_ROOT)
    verify_additive(_REPO_ROOT)


def test_snapshot_shape_is_additive_over_v1_0() -> None:
    snapshot = build_snapshot()
    assert snapshot["api_version"] == "1.1"
    assert snapshot["base_api_version"] == "1.0"
    assert len(snapshot["v1_0_symbols"]) == 56
    for name in (
        "InstrumentId",
        "UniverseSpec",
        "PortfolioProtocol",
        "PortfolioResult",
        "PortfolioCheckpoint",
        "run_portfolio_simulation",
        "resume_portfolio_simulation",
        "verify_portfolio_result",
        "build_market_panel",
    ):
        assert name in snapshot["m4b_symbols"], name
    # additive: no M4B symbol shadows a v1.0 name.
    assert set(snapshot["m4b_symbols"]) & set(snapshot["v1_0_symbols"]) == set()


def _staged_repo(tmp_path: Path) -> Path:
    (tmp_path / "research" / "m4a").mkdir(parents=True)
    (tmp_path / "research" / "m4b").mkdir(parents=True)
    (tmp_path / M4A_SNAPSHOT_RELPATH).write_bytes((_REPO_ROOT / M4A_SNAPSHOT_RELPATH).read_bytes())
    (tmp_path / SNAPSHOT_RELPATH).write_bytes(snapshot_bytes())
    return tmp_path


def test_verify_detects_a_stale_v1_1_snapshot(tmp_path: Path) -> None:
    repo = _staged_repo(tmp_path)
    payload = strict_load_canonical((repo / SNAPSHOT_RELPATH).read_bytes(), "m4b")
    assert isinstance(payload, dict)
    payload["m4b_symbols"].pop("InstrumentId")  # drift: a symbol dropped
    (repo / SNAPSHOT_RELPATH).write_bytes(canonical_json_bytes(payload))
    with pytest.raises(PublicAPIDriftError, match="was not regenerated"):
        verify(repo)


def test_verify_additive_detects_a_mutated_v1_0_layer(tmp_path: Path) -> None:
    repo = _staged_repo(tmp_path)
    m4a = strict_load_canonical((repo / M4A_SNAPSHOT_RELPATH).read_bytes(), "m4a")
    assert isinstance(m4a, dict)
    m4a["symbols"]["API_VERSION"]["value"] = "9.9"  # pretend a v1.0 symbol changed
    (repo / M4A_SNAPSHOT_RELPATH).write_bytes(canonical_json_bytes(m4a))
    with pytest.raises(PublicAPIDriftError, match="not additive"):
        verify_additive(repo)


def test_verify_reports_a_missing_snapshot(tmp_path: Path) -> None:
    (tmp_path / "research" / "m4a").mkdir(parents=True)
    (tmp_path / M4A_SNAPSHOT_RELPATH).write_bytes((_REPO_ROOT / M4A_SNAPSHOT_RELPATH).read_bytes())
    with pytest.raises(PublicAPIDriftError, match="missing"):
        verify(tmp_path)
