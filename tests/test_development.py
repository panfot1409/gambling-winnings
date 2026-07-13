"""The Milestone 3A development firewall: research-train only, forbidden sealed.

The firewall must hand downstream code exactly the research-train partition
(2221 rows through 2022-06-21 UTC) and reject any frame or context carrying
a development-gate or final-holdout row — never silently truncating.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.data.builder import load_canonical_dataset
from eth_research.development import (
    DEVELOPMENT_GATE,
    FINAL_HOLDOUT,
    RESEARCH_TRAIN,
    DevelopmentAccessError,
    DevelopmentPartition,
    build_development_partition,
    guard_context,
    guard_research_train_frame,
    load_development_dataset,
    load_development_partition,
    verify_development_partition,
)
from eth_research.replay_m2b import reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
PARTITION_PATH = REPO_ROOT / "research/m3a/development_partition.json"
RESEARCH_TRAIN_LAST = pd.Timestamp("2022-06-21", tz="UTC")
GATE_FIRST = pd.Timestamp("2022-06-22", tz="UTC")
HOLDOUT_FIRST = pd.Timestamp("2024-07-01", tz="UTC")

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def real_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("m3a_dev")
    return reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path


@pytest.fixture(scope="module")
def full_frame(real_manifest: Path) -> pd.DataFrame:
    return load_canonical_dataset(real_manifest).frame


class TestPartitionDerivation:
    def test_three_levels_have_exact_counts_and_bounds(self, real_manifest: Path) -> None:
        part = build_development_partition(REPO_ROOT, real_manifest)
        rt, gate, holdout = part.partitions
        assert (rt.name, rt.row_count) == (RESEARCH_TRAIN, 2221)
        assert (gate.name, gate.row_count) == (DEVELOPMENT_GATE, 740)
        assert (holdout.name, holdout.row_count) == (FINAL_HOLDOUT, 741)
        assert rt.last_open_time == RESEARCH_TRAIN_LAST
        assert gate.first_open_time == GATE_FIRST
        assert holdout.first_open_time == HOLDOUT_FIRST
        assert holdout.last_open_time == pd.Timestamp("2026-07-11", tz="UTC")

    def test_committed_partition_recomputes_byte_for_byte(self, real_manifest: Path) -> None:
        committed = PARTITION_PATH.read_bytes()
        assert committed == build_development_partition(REPO_ROOT, real_manifest).to_json_bytes()
        # And the dedicated verifier accepts it.
        verify_development_partition(REPO_ROOT, real_manifest)

    def test_partition_binds_the_frozen_m2_dossier(self, real_manifest: Path) -> None:
        from eth_research.data.provenance import sha256_file

        part = load_development_partition(PARTITION_PATH)
        assert part.frozen_m2_dossier_sha256 == sha256_file(
            REPO_ROOT / "research/m2b/frozen_dossier.json"
        )
        assert part.dataset_row_count == 3702

    def test_round_trips_byte_stably(self) -> None:
        part = load_development_partition(PARTITION_PATH)
        assert part.to_json_bytes() == PARTITION_PATH.read_bytes()

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(PARTITION_PATH.read_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            DevelopmentPartition.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_partitions_must_sum_to_dataset(self) -> None:
        payload = json.loads(PARTITION_PATH.read_bytes())
        payload["dataset_row_count"] = 9999
        with pytest.raises(ValueError, match="do not sum to dataset rows"):
            DevelopmentPartition.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestFirewallHandsResearchTrainOnly:
    def test_development_dataset_is_exactly_research_train(self, real_manifest: Path) -> None:
        dds = load_development_dataset(REPO_ROOT, real_manifest)
        assert len(dds.frame) == 2221
        assert dds.frame.index[0] == pd.Timestamp("2016-05-23", tz="UTC")
        assert dds.frame.index[-1] == RESEARCH_TRAIN_LAST
        assert dds.research_train_last_open_time == RESEARCH_TRAIN_LAST
        # Not one forbidden row.
        assert dds.frame.index.max() < GATE_FIRST

    def test_no_forbidden_timestamp_in_the_handed_frame(self, real_manifest: Path) -> None:
        dds = load_development_dataset(REPO_ROOT, real_manifest)
        assert (dds.frame.index < GATE_FIRST).all()
        assert (dds.frame.index < HOLDOUT_FIRST).all()


class TestFirewallRejectsForbiddenAccess:
    def test_a_single_development_gate_row_is_rejected(self, full_frame: pd.DataFrame) -> None:
        # Research train plus exactly one gate row: rejected, never truncated.
        through_gate = full_frame.loc[full_frame.index <= GATE_FIRST]
        assert through_gate.index[-1] == GATE_FIRST
        with pytest.raises(DevelopmentAccessError, match="forbidden partition access"):
            guard_research_train_frame(through_gate, RESEARCH_TRAIN_LAST)

    def test_a_final_holdout_row_is_rejected(self, full_frame: pd.DataFrame) -> None:
        with pytest.raises(DevelopmentAccessError, match="forbidden partition access"):
            guard_research_train_frame(full_frame, RESEARCH_TRAIN_LAST)

    def test_the_whole_dataset_is_rejected_not_truncated(self, full_frame: pd.DataFrame) -> None:
        with pytest.raises(DevelopmentAccessError):
            guard_research_train_frame(full_frame, RESEARCH_TRAIN_LAST)

    def test_context_crossing_the_boundary_is_rejected(self, full_frame: pd.DataFrame) -> None:
        crossing = full_frame.loc[
            (full_frame.index >= pd.Timestamp("2022-06-01", tz="UTC"))
            & (full_frame.index <= GATE_FIRST)
        ]
        with pytest.raises(DevelopmentAccessError, match="forbidden partition access"):
            guard_context(crossing, RESEARCH_TRAIN_LAST)

    def test_clean_research_train_context_passes(self, full_frame: pd.DataFrame) -> None:
        clean = full_frame.loc[full_frame.index <= RESEARCH_TRAIN_LAST].iloc[-55:]
        guard_context(clean, RESEARCH_TRAIN_LAST)  # must not raise
        guard_context(None, RESEARCH_TRAIN_LAST)

    def test_shuffled_frame_is_rejected(self, full_frame: pd.DataFrame) -> None:
        rt = full_frame.loc[full_frame.index <= RESEARCH_TRAIN_LAST].copy()
        shuffled = rt.iloc[[2, 0, 1, *range(3, len(rt))]]
        with pytest.raises(DevelopmentAccessError, match="strict OHLCV validation"):
            guard_research_train_frame(shuffled, RESEARCH_TRAIN_LAST)

    def test_duplicate_timestamp_is_rejected(self, full_frame: pd.DataFrame) -> None:
        rt = full_frame.loc[full_frame.index <= RESEARCH_TRAIN_LAST]
        dup = pd.concat([rt, rt.iloc[[-1]]])
        with pytest.raises(DevelopmentAccessError):
            guard_research_train_frame(dup, RESEARCH_TRAIN_LAST)

    def test_empty_frame_is_rejected(self) -> None:
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        with pytest.raises(DevelopmentAccessError, match="empty"):
            guard_research_train_frame(empty, RESEARCH_TRAIN_LAST)

    def test_forged_partition_fingerprint_is_rejected(self, real_manifest: Path) -> None:
        # A partition whose research-train fingerprint has been altered will
        # not match the frame the firewall slices.
        dataset = load_canonical_dataset(real_manifest)
        part = load_development_partition(PARTITION_PATH)
        payload = json.loads(part.to_json_bytes())
        payload["partitions"][0]["content_fingerprint"] = "sha256:" + "f" * 64
        forged = DevelopmentPartition.from_json_bytes(json.dumps(payload).encode("utf-8"))
        from eth_research.development import DevelopmentDataset

        rt = dataset.frame.loc[dataset.frame.index <= RESEARCH_TRAIN_LAST].copy()
        with pytest.raises(DevelopmentAccessError, match="fingerprint"):
            DevelopmentDataset(frame=rt, partition=forged)
