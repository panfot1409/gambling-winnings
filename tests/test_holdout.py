"""Durable holdout identity and the freshness-conflict policy (P0).

These tests pin the defect the milestone closes: a consumed one-time test
holdout must stay consumed even when the protocol, lock, package version,
schema, evaluation id, commit, or runtime changes. Freshness is a property
of the *candles*, recorded as a durable :class:`HoldoutIdentity`, not of a
mutable ``(dataset_lock, protocol)`` pair.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import eth_research
from conftest import CoinbasePipeline
from eth_research import evaluation
from eth_research.data.builder import load_canonical_dataset
from eth_research.data.lock import build_dataset_lock
from eth_research.data.provenance import DatasetIdentity, content_fingerprint
from eth_research.holdout import (
    HOLDOUT_FINGERPRINT_ALGORITHM,
    HOLDOUT_SCHEMA_VERSION,
    HoldoutIdentity,
    build_holdout_identity,
    find_holdout_conflicts,
    holdout_test_fingerprint,
)
from eth_research.ledger import LEDGER_SCHEMA_VERSION, LedgerEvent
from eth_research.protocol import (
    SPLIT_SEMANTICS,
    TRAIN_FRACTION,
    VALIDATION_FRACTION,
    build_benchmark_protocol,
)
from eth_research.splits import chronological_split

DAY = pd.Timedelta(days=1)
T0 = pd.Timestamp("2026-07-11T19:00:00+00:00")


def make_holdout(**overrides: Any) -> HoldoutIdentity:
    fields: dict[str, Any] = {
        "holdout_schema_version": HOLDOUT_SCHEMA_VERSION,
        "base_asset": "ETH",
        "quote_asset": "USD",
        "symbol": "ETH-USD",
        "venue": "Coinbase Exchange",
        "market_type": "spot",
        "candle_interval": DAY,
        "dataset_content_fingerprint": "sha256:" + "1" * 64,
        "test_content_fingerprint": "sha256:" + "e" * 64,
        "test_first_open_time": pd.Timestamp("2024-07-01", tz="UTC"),
        "test_last_open_time": pd.Timestamp("2024-07-01", tz="UTC") + 740 * DAY,
        "test_row_count": 741,
        "split_semantics": SPLIT_SEMANTICS,
        "train_fraction": TRAIN_FRACTION,
        "validation_fraction": VALIDATION_FRACTION,
        "fingerprint_algorithm": HOLDOUT_FINGERPRINT_ALGORITHM,
    }
    fields.update(overrides)
    return HoldoutIdentity(**fields)


# Distinct fingerprints so a proposed holdout can only collide on the
# temporal-overlap dimension, never on an exact-match one.
DISTINCT = {
    "dataset_content_fingerprint": "sha256:" + "c" * 64,
    "test_content_fingerprint": "sha256:" + "d" * 64,
}


def windowed(first: pd.Timestamp, n: int, **overrides: Any) -> HoldoutIdentity:
    """A holdout over an ``n``-candle daily window starting at ``first``."""
    return make_holdout(
        test_first_open_time=first,
        test_last_open_time=first + (n - 1) * DAY,
        test_row_count=n,
        **overrides,
    )


def ledger_event_for(
    holdout: HoldoutIdentity,
    *,
    event: str = "started",
    evaluation_id: str = "m2b-test-eval-001",
    **overrides: Any,
) -> LedgerEvent:
    """A ledger event recording an access to ``holdout`` (mirrors the evaluator)."""
    completed = event == "completed"
    fields: dict[str, Any] = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "event": event,
        "evaluation_id": evaluation_id,
        "holdout_id": holdout.holdout_id,
        "dataset_content_fingerprint": holdout.dataset_content_fingerprint,
        "test_content_fingerprint": holdout.test_content_fingerprint,
        "symbol": holdout.symbol,
        "venue": holdout.venue,
        "candle_interval": holdout.candle_interval,
        "test_first_open_time": holdout.test_first_open_time,
        "test_last_open_time": holdout.test_last_open_time,
        "test_row_count": holdout.test_row_count,
        "dataset_lock_sha256": "2" * 64,
        "protocol_sha256": "3" * 64,
        "runtime_contract_sha256": "6" * 64,
        "code_commit_sha": "a" * 40,
        "reason": "authorized one-time",
        "event_time_utc": T0,
        "results_json_sha256": "4" * 64 if completed else None,
        "report_markdown_sha256": "5" * 64 if completed else None,
        "result_bundle_sha256": "9" * 64 if completed else None,
        "failure_description": "engine raised" if event == "failed" else None,
    }
    fields.update(overrides)
    return LedgerEvent(**fields)


class TestHoldoutIdentityModel:
    def test_round_trips_byte_stably(self) -> None:
        holdout = make_holdout()
        restored = HoldoutIdentity.from_json_bytes(holdout.to_json_bytes())
        assert restored == holdout
        assert restored.to_json_bytes() == holdout.to_json_bytes()

    def test_holdout_id_is_a_stable_hex64(self) -> None:
        holdout = make_holdout()
        assert holdout.holdout_id == make_holdout().holdout_id
        assert len(holdout.holdout_id) == 64
        assert all(c in "0123456789abcdef" for c in holdout.holdout_id)

    def test_changing_any_field_changes_the_id(self) -> None:
        base = make_holdout().holdout_id
        assert make_holdout(test_content_fingerprint="sha256:" + "a" * 64).holdout_id != base
        assert make_holdout(symbol="ETH-USDC").holdout_id != base

    def test_unknown_key_is_rejected(self) -> None:
        import json

        payload = json.loads(make_holdout().to_json_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            HoldoutIdentity.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_pinned_split_fields_are_enforced(self) -> None:
        with pytest.raises(ValueError, match="split_semantics is pinned"):
            make_holdout(split_semantics="whatever")
        with pytest.raises(ValueError, match="train_fraction is pinned"):
            make_holdout(train_fraction=0.5)
        with pytest.raises(ValueError, match="fingerprint algorithm"):
            make_holdout(fingerprint_algorithm="ohlcv-fp-v1/sha256")

    def test_non_fingerprint_test_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="test_content_fingerprint"):
            make_holdout(test_content_fingerprint="deadbeef")

    def test_inconsistent_test_bounds_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="inconsistent with test_first_open_time"):
            make_holdout(test_row_count=740)

    def test_bad_base_asset_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="base_asset must be 'ETH'"):
            make_holdout(base_asset="BTC")


class TestHoldoutFingerprint:
    def test_is_deterministic(self, coinbase_pipeline: CoinbasePipeline) -> None:
        dataset = load_canonical_dataset(coinbase_pipeline.build.manifest_path)
        test = chronological_split(dataset.frame).test
        first = holdout_test_fingerprint(test, coinbase_pipeline.identity)
        second = holdout_test_fingerprint(test, coinbase_pipeline.identity)
        assert first == second
        assert first.startswith("sha256:")

    def test_binds_the_instrument_identity(self, coinbase_pipeline: CoinbasePipeline) -> None:
        dataset = load_canonical_dataset(coinbase_pipeline.build.manifest_path)
        test = chronological_split(dataset.frame).test
        base = holdout_test_fingerprint(test, coinbase_pipeline.identity)
        other = DatasetIdentity(
            quote_asset="USD",
            symbol="ETH-USDC",  # different symbol, same candles
            venue=coinbase_pipeline.identity.venue,
            interval=coinbase_pipeline.identity.interval,
            source=coinbase_pipeline.identity.source,
        )
        assert holdout_test_fingerprint(test, other) != base

    def test_is_domain_separated_from_dataset_fingerprint(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_canonical_dataset(coinbase_pipeline.build.manifest_path)
        test = chronological_split(dataset.frame).test
        holdout_fp = holdout_test_fingerprint(test, coinbase_pipeline.identity)
        # Same rows, but the plain content fingerprint has a different domain
        # header and no identity binding — the two must never collide.
        assert holdout_fp != content_fingerprint(test)

    def test_non_canonical_frame_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        with pytest.raises(ValueError, match="validated canonical frame"):
            holdout_test_fingerprint(pd.DataFrame({"open": [1.0]}), coinbase_pipeline.identity)


class TestBuildHoldoutIdentity:
    def test_matches_the_chronological_split_test_segment(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_canonical_dataset(coinbase_pipeline.build.manifest_path)
        protocol = build_benchmark_protocol(
            build_dataset_lock(
                coinbase_pipeline.build.manifest,
                manifest_sha256=coinbase_pipeline.manifest_sha256,
                acquisition_evidence_sha256=coinbase_pipeline.evidence_sha256,
            ),
            package_version=eth_research.__version__,
        )
        holdout = build_holdout_identity(dataset, protocol)
        test = chronological_split(dataset.frame).test
        assert holdout.test_first_open_time == test.index[0]
        assert holdout.test_last_open_time == test.index[-1]
        assert holdout.test_row_count == len(test)
        assert holdout.dataset_content_fingerprint == dataset.manifest.content_fingerprint
        assert holdout.test_content_fingerprint == holdout_test_fingerprint(
            test, coinbase_pipeline.identity
        )

    def test_builds_without_running_the_engine(
        self, coinbase_pipeline: CoinbasePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Integrity-only: deriving the holdout identity reads/hashes the test
        # candles but must never run a backtest. Poison the engine and confirm
        # the build still succeeds.
        def forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("build_holdout_identity must not run the engine")

        monkeypatch.setattr(evaluation, "run_backtest", forbidden)
        import eth_research.backtest as backtest_module

        monkeypatch.setattr(backtest_module, "run_backtest", forbidden)
        dataset = load_canonical_dataset(coinbase_pipeline.build.manifest_path)
        protocol = build_benchmark_protocol(
            build_dataset_lock(
                coinbase_pipeline.build.manifest,
                manifest_sha256=coinbase_pipeline.manifest_sha256,
                acquisition_evidence_sha256=coinbase_pipeline.evidence_sha256,
            ),
            package_version=eth_research.__version__,
        )
        holdout = build_holdout_identity(dataset, protocol)
        assert holdout.test_row_count == 24


class TestFindHoldoutConflicts:
    def test_empty_ledger_has_no_conflict(self) -> None:
        assert find_holdout_conflicts((), make_holdout()) == ()

    def test_changing_protocol_or_lock_does_not_launder_the_holdout(self) -> None:
        # The confirmed P0: the same candles read as fresh once the protocol
        # hash changed. Here a prior access exists; a second attempt on the
        # SAME candles (under any protocol/lock/runtime — those are not part of
        # the holdout identity) still conflicts.
        holdout = make_holdout()
        prior = ledger_event_for(holdout, protocol_sha256="3" * 64, dataset_lock_sha256="2" * 64)
        conflicts = find_holdout_conflicts((prior,), holdout)
        assert conflicts, "the consumed holdout must not be launderable by changing metadata"
        assert conflicts[0].reasons == (
            "same holdout identity",
            "same dataset content fingerprint",
            "same test content fingerprint",
            "overlapping test window for the same instrument",
        )

    def test_same_dataset_fingerprint_conflicts_even_if_test_digest_differs(self) -> None:
        prior = ledger_event_for(make_holdout())
        # A different declared test digest but the same dataset content: still
        # the same underlying data — refuse.
        proposed = make_holdout(test_content_fingerprint="sha256:" + "b" * 64)
        conflicts = find_holdout_conflicts((prior,), proposed)
        assert conflicts
        assert "same dataset content fingerprint" in conflicts[0].reasons

    def test_same_test_fingerprint_conflicts_even_if_dataset_grew(self) -> None:
        prior = ledger_event_for(make_holdout())
        # A superset dataset (different content fingerprint) whose test segment
        # is byte-identical to the consumed one — refuse on the test digest.
        proposed = make_holdout(dataset_content_fingerprint="sha256:" + "c" * 64)
        conflicts = find_holdout_conflicts((prior,), proposed)
        assert conflicts
        assert "same test content fingerprint" in conflicts[0].reasons

    def test_a_genuinely_distinct_holdout_is_allowed(self) -> None:
        prior = ledger_event_for(make_holdout())
        proposed = make_holdout(
            dataset_content_fingerprint="sha256:" + "c" * 64,
            test_content_fingerprint="sha256:" + "d" * 64,
            symbol="ETH-EUR",
        )
        assert find_holdout_conflicts((prior,), proposed) == ()

    @pytest.mark.parametrize("event", ["started", "completed", "failed"])
    def test_any_event_type_consumes_the_holdout(self, event: str) -> None:
        prior = ledger_event_for(make_holdout(), event=event)
        assert find_holdout_conflicts((prior,), make_holdout())


class TestTemporalOverlapProtection:
    """A grown/trimmed dataset changes both fingerprints, but an overlapping
    test window on the same instrument must still be refused."""

    D0 = pd.Timestamp("2024-07-01", tz="UTC")

    def _prior(self) -> LedgerEvent:
        return ledger_event_for(windowed(self.D0, 10))

    def test_partial_overlap_is_refused(self) -> None:
        proposed = windowed(self.D0 + 5 * DAY, 10, **DISTINCT)
        conflicts = find_holdout_conflicts((self._prior(),), proposed)
        assert conflicts
        assert conflicts[0].reasons == ("overlapping test window for the same instrument",)

    def test_proposed_contained_in_prior_is_refused(self) -> None:
        prior = ledger_event_for(windowed(self.D0, 20))
        proposed = windowed(self.D0 + 5 * DAY, 5, **DISTINCT)
        assert find_holdout_conflicts((prior,), proposed)

    def test_prior_contained_in_proposed_is_refused(self) -> None:
        prior = ledger_event_for(windowed(self.D0 + 5 * DAY, 5))
        proposed = windowed(self.D0, 20, **DISTINCT)
        assert find_holdout_conflicts((prior,), proposed)

    def test_single_shared_candle_is_refused(self) -> None:
        # Prior ends at D0+9; proposed starts at D0+9 — one shared open.
        proposed = windowed(self.D0 + 9 * DAY, 10, **DISTINCT)
        assert find_holdout_conflicts((self._prior(),), proposed)

    def test_adjacent_but_disjoint_window_is_allowed(self) -> None:
        # Prior ends at D0+9; proposed starts one interval later at D0+10.
        proposed = windowed(self.D0 + 10 * DAY, 10, **DISTINCT)
        assert find_holdout_conflicts((self._prior(),), proposed) == ()

    def test_same_window_different_venue_is_allowed(self) -> None:
        proposed = windowed(self.D0, 10, venue="OtherVenue", **DISTINCT)
        assert find_holdout_conflicts((self._prior(),), proposed) == ()

    def test_same_window_different_interval_is_allowed(self) -> None:
        first = self.D0
        proposed = make_holdout(
            candle_interval=pd.Timedelta(hours=12),
            test_first_open_time=first,
            test_last_open_time=first + 9 * pd.Timedelta(hours=12),
            test_row_count=10,
            **DISTINCT,
        )
        assert find_holdout_conflicts((self._prior(),), proposed) == ()
