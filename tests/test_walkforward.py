"""Walk-forward protocol: exact folds, byte reproducibility, attack matrix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research.development import load_development_dataset
from eth_research.replay_m2b import reconstruct_dataset
from eth_research.walkforward import (
    WALK_FORWARD_PROTOCOL_RELPATH,
    WalkForwardProtocol,
    build_fold_frames,
    build_walk_forward_protocol,
    load_walk_forward_protocol,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
PROTOCOL_PATH = REPO_ROOT / WALK_FORWARD_PROTOCOL_RELPATH

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def research_train() -> pd.DataFrame:
    import tempfile

    work = Path(tempfile.mkdtemp())
    manifest = reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path
    return load_development_dataset(REPO_ROOT, manifest).frame


def _tamper(**changes: Any) -> bytes:
    payload = json.loads(PROTOCOL_PATH.read_bytes())
    payload.update(changes)
    return json.dumps(payload).encode("utf-8")


class TestProtocolStructure:
    def test_committed_recomputes_byte_for_byte(self, research_train: pd.DataFrame) -> None:
        committed = load_walk_forward_protocol(PROTOCOL_PATH)
        # The protocol content is version-independent: rebuild with the
        # committed recorded version so a later package bump stays byte-identical.
        rebuilt = build_walk_forward_protocol(
            research_train,
            development_partition_sha256=committed.development_partition_sha256,
            package_version=committed.package_version,
        )
        assert rebuilt.to_json_bytes() == PROTOCOL_PATH.read_bytes()

    def test_five_expanding_folds_cover_1126_oos_rows(self) -> None:
        proto = load_walk_forward_protocol(PROTOCOL_PATH)
        assert len(proto.folds) == 5
        assert [f.oos_row_count for f in proto.folds] == [226, 225, 225, 225, 225]
        trains = [f.training_row_count for f in proto.folds]
        assert trains == [1095, 1321, 1546, 1771, 1996]
        assert sum(f.oos_row_count for f in proto.folds) == 1126

    def test_round_trips_byte_stably(self) -> None:
        proto = load_walk_forward_protocol(PROTOCOL_PATH)
        assert proto.to_json_bytes() == PROTOCOL_PATH.read_bytes()

    def test_fold_frames_have_context_before_oos_and_no_overlap(
        self, research_train: pd.DataFrame
    ) -> None:
        proto = load_walk_forward_protocol(PROTOCOL_PATH)
        frames = build_fold_frames(research_train, proto)
        seen: set[pd.Timestamp] = set()
        for ff in frames:
            assert ff.context.index[-1] < ff.oos.index[0]
            assert ff.training.index[-1] < ff.oos.index[0]
            assert len(ff.context) <= 55
            fold_set = set(ff.oos.index)
            assert not (fold_set & seen), "OOS overlap between folds"
            seen |= fold_set
        assert len(seen) == 1126


class TestAttackMatrix:
    """Part VII: every structural corruption of the protocol is rejected."""

    def test_wrong_initial_training_count(self) -> None:
        with pytest.raises(ValueError, match="initial_training_rows is pinned"):
            WalkForwardProtocol.from_json_bytes(_tamper(initial_training_rows=1000))

    def test_wrong_fold_count(self) -> None:
        with pytest.raises(ValueError, match="oos_fold_count is pinned"):
            WalkForwardProtocol.from_json_bytes(_tamper(oos_fold_count=6))

    def test_nonzero_information_gap(self) -> None:
        with pytest.raises(ValueError, match="information_gap_bars is pinned"):
            WalkForwardProtocol.from_json_bytes(_tamper(information_gap_bars=1))

    def test_changed_research_train_count(self) -> None:
        with pytest.raises(ValueError, match="research_train_row_count is pinned"):
            WalkForwardProtocol.from_json_bytes(_tamper(research_train_row_count=2222))

    def test_changed_fingerprint_then_folds_still_validate_but_model_differs(self) -> None:
        # A changed fingerprint parses (it is a fingerprint) but will not match
        # the recomputed protocol — reproduction catches it. Structurally the
        # model still validates, so we assert the reproduction mismatch.
        tampered = WalkForwardProtocol.from_json_bytes(
            _tamper(research_train_content_fingerprint="sha256:" + "f" * 64)
        )
        assert tampered.to_json_bytes() != PROTOCOL_PATH.read_bytes()

    def test_overlapping_folds(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        # Make fold 1 start before fold 0 ends.
        payload["folds"][1]["oos_first_open_time"] = payload["folds"][0]["oos_first_open_time"]
        with pytest.raises(ValueError, match="overlaps the previous fold"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_broken_expanding_training(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"][2]["training_row_count"] = 9999
        with pytest.raises(ValueError, match="expanding expectation"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_reversed_fold_indices(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"] = list(reversed(payload["folds"]))
        with pytest.raises(ValueError, match="fold indices must be"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_duplicate_fold_index(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"][1]["fold_index"] = 0
        with pytest.raises(ValueError, match="fold indices must be"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_missing_oos_row_breaks_coverage(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"][4]["oos_row_count"] = 224  # one short: coverage gap
        with pytest.raises(ValueError, match="do not cover the research-train partition"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_extra_oos_row_is_rejected(self) -> None:
        # Enlarging fold 0's OOS shifts every later fold's expanding-training
        # expectation, so the corruption is caught (whether at the expanding
        # check or the coverage check) — never silently accepted.
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"][0]["oos_row_count"] = 227
        with pytest.raises(ValueError, match=r"expanding expectation|do not cover"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_off_by_one_context_over_cap(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["folds"][0]["context_row_count"] = 56
        with pytest.raises(ValueError, match="exceeds the 55-bar cap"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_extra_cost_scenario_is_rejected(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["cost_scenarios"].append({"name": "base", "fee_rate": 0.0, "slippage_rate": 0.0})
        with pytest.raises(ValueError, match="three pinned scenarios"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_changed_bootstrap_seed_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="bootstrap_seed is pinned"):
            WalkForwardProtocol.from_json_bytes(_tamper(bootstrap_seed=1))

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"unknown=\['surprise'\]"):
            WalkForwardProtocol.from_json_bytes(_tamper(surprise=1))

    def test_extra_strategy_is_rejected(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["strategies"] = [*payload["strategies"], "donchian_20_10"]
        with pytest.raises(ValueError, match="strategies are pinned"):
            WalkForwardProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))
