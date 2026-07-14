"""The Milestone 3B integrity-only research-train loader.

``verify_dataset_integrity_only`` must hand back exactly the research-train
partition (2221 rows through 2022-06-21 UTC) after binding the committed
dataset to the frozen M2B dossier's anchors — and it must do so **without ever
running the M2B train/validation benchmark**. No strategy, execution engine,
cost model, metric, bootstrap, or report may be called while verifying: poison
spies installed on every one of those callbacks must remain unfired (the
disclosed M3A ``4.1-1`` behaviour is exactly what this loader avoids).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.development import (
    DEVELOPMENT_PARTITION_RELPATH,
    FROZEN_M2_DOSSIER_RELPATH,
    load_development_partition,
)
from eth_research.dossier import FrozenResearchDossier, load_frozen_dossier
from eth_research.fractional import dataset as ds
from eth_research.fractional.dataset import (
    DatasetIntegrityError,
    DatasetIntegrityResult,
    verify_dataset_integrity_only,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
RESEARCH_TRAIN_FIRST = pd.Timestamp("2016-05-23", tz="UTC")
RESEARCH_TRAIN_LAST = pd.Timestamp("2022-06-21", tz="UTC")
GATE_FIRST = pd.Timestamp("2022-06-22", tz="UTC")
HOLDOUT_FIRST = pd.Timestamp("2024-07-01", tz="UTC")

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def result() -> DatasetIntegrityResult:
    return verify_dataset_integrity_only(REPO_ROOT)


class TestExposesResearchTrainOnly:
    def test_exactly_the_research_train_rows(self, result: DatasetIntegrityResult) -> None:
        frame = result.research_train
        assert len(frame) == 2221
        assert frame.index[0] == RESEARCH_TRAIN_FIRST
        assert frame.index[-1] == RESEARCH_TRAIN_LAST
        assert result.research_train_last_open_time == RESEARCH_TRAIN_LAST

    def test_not_one_forbidden_row_is_returned(self, result: DatasetIntegrityResult) -> None:
        frame = result.research_train
        assert (frame.index < GATE_FIRST).all()
        assert (frame.index < HOLDOUT_FIRST).all()
        assert frame.index.max() < GATE_FIRST

    def test_partition_is_the_committed_bytes(self, result: DatasetIntegrityResult) -> None:
        committed = load_development_partition(REPO_ROOT / DEVELOPMENT_PARTITION_RELPATH)
        assert result.partition.to_json_bytes() == committed.to_json_bytes()

    def test_binds_the_frozen_m2b_dossier_in_snapshot_mode(
        self, result: DatasetIntegrityResult
    ) -> None:
        # The running 0.5.0 package verifies the frozen 0.3.0 dossier as a snapshot.
        assert result.dossier.package_version == "0.3.0"
        assert "snapshot_mode" in result.checks

    def test_reports_every_integrity_check(self, result: DatasetIntegrityResult) -> None:
        for expected in (
            "raw_to_derived_reconstructed",
            "canonical_ohlcv_revalidated",
            "anchor:dataset_manifest",
            "anchor:dataset_content_fingerprint",
            "anchor:derived_csv",
            "dataset_lock_chain",
            "protocol_verified",
            "version_chain",
            "partition_recomputed",
            "partition_binds_dossier",
            "research_train_exposed",
        ):
            assert expected in result.checks


class TestNoBenchmarkDuringIntegrityLoad:
    """The integrity-only load must never touch the engine/metric/bootstrap/
    report — the M2B benchmark path. Poison every one of those callbacks."""

    def test_engine_metric_bootstrap_report_stay_unfired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import eth_research.backtest as backtest
        import eth_research.bootstrap as bootstrap
        import eth_research.bootstrap_v2 as bootstrap_v2
        import eth_research.evaluation as evaluation
        import eth_research.m2b_report as m2b_report
        import eth_research.metrics as metrics

        fired: list[str] = []

        def poison(name: str):  # type: ignore[no-untyped-def]
            def spy(*args: object, **kwargs: object) -> object:
                fired.append(name)
                raise AssertionError(f"integrity-only load must not call {name}")

            return spy

        # monkeypatch.setattr defaults to raising if the attribute is absent,
        # so a typo here fails the test rather than silently no-op'ing — every
        # patched name is proven to be a real callback. Strategies are reached
        # only through run_backtest, so poisoning it covers signal generation.
        targets = {
            (backtest, "run_backtest"),
            (evaluation, "evaluate_train_validation"),
            (evaluation, "evaluate_train_validation_from_manifest"),
            (evaluation, "_run_segment"),
            (evaluation, "run_authorized_benchmark"),
            (metrics, "summarize"),
            (bootstrap, "moving_block_bootstrap"),
            (bootstrap_v2, "fold_stratified_moving_block_bootstrap"),
            (bootstrap_v2, "hierarchical_fold_block_bootstrap"),
            (m2b_report, "render_report"),
        }
        installed = {}
        for module, name in targets:
            spy = poison(f"{module.__name__}.{name}")
            monkeypatch.setattr(module, name, spy)
            installed[(module.__name__, name)] = spy

        # The patches are actually in place, so "unfired" is a meaningful claim.
        assert backtest.run_backtest is installed[("eth_research.backtest", "run_backtest")]
        assert metrics.summarize is installed[("eth_research.metrics", "summarize")]

        result = verify_dataset_integrity_only(REPO_ROOT)

        assert fired == []
        assert len(result.research_train) == 2221


class TestAnchorTamperIsRejected:
    """A dossier whose anchors disagree with the committed bytes is rejected —
    injected here so no committed file is mutated on disk."""

    def _inject(self, monkeypatch: pytest.MonkeyPatch, forged: FrozenResearchDossier) -> None:
        # Patch the name the loader actually calls (bound in the dataset module).
        monkeypatch.setattr(ds, "load_frozen_dossier", lambda *a, **k: forged)

    def _real(self) -> FrozenResearchDossier:
        return load_frozen_dossier(REPO_ROOT / FROZEN_M2_DOSSIER_RELPATH)

    def test_tampered_derived_csv_anchor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(monkeypatch, dataclasses.replace(self._real(), derived_csv_sha256="0" * 64))
        with pytest.raises(DatasetIntegrityError, match="derived_csv"):
            verify_dataset_integrity_only(REPO_ROOT)

    def test_tampered_manifest_anchor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch, dataclasses.replace(self._real(), dataset_manifest_sha256="0" * 64)
        )
        with pytest.raises(DatasetIntegrityError, match="anchor:dataset_manifest"):
            verify_dataset_integrity_only(REPO_ROOT)

    def test_tampered_content_fingerprint_anchor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch,
            dataclasses.replace(self._real(), dataset_content_fingerprint="sha256:" + "0" * 64),
        )
        with pytest.raises(DatasetIntegrityError, match="content_fingerprint"):
            verify_dataset_integrity_only(REPO_ROOT)

    def test_tampered_raw_bundle_fingerprint_anchor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._inject(
            monkeypatch,
            dataclasses.replace(self._real(), raw_bundle_fingerprint="sha256:" + "0" * 64),
        )
        with pytest.raises(DatasetIntegrityError, match="raw_bundle_fingerprint"):
            verify_dataset_integrity_only(REPO_ROOT)
