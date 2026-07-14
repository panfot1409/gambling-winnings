"""The frozen M3C protocol pins every constant and rejects tampering.

The protocol is built once from the real research-train partition (research-train
rows only) and the committed walk-forward folds; construction is a cheap in-memory
derivation and writes no artifact file.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.cost_model import SCENARIOS
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.m3c.candidate import (
    CANDIDATE_FINGERPRINT,
    M3C_CANDIDATE_ID,
    M3C_MAX_CONTEXT_BARS,
    M3C_STRATEGY_NAMES,
)
from eth_research.m3c.protocol import (
    EMPTY_SHA256,
    M3CProtocol,
    ProtocolError,
    build_m3c_protocol,
    load_m3c_protocol,
)
from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_ALGORITHM,
    M3C_BOOTSTRAP_CONFIDENCE,
    M3C_BOOTSTRAP_RESAMPLES,
    M3C_BOOTSTRAP_SEED,
)
from eth_research.walkforward import (
    INITIAL_CASH,
    WALK_FORWARD_PROTOCOL_RELPATH,
    load_walk_forward_protocol,
)

REPO = Path(eth_research.__file__).resolve().parents[2]
_REJECT = (ValueError, TypeError)
_SCEN = tuple(s.name for s in SCENARIOS)

_RESEARCH_TRAIN = verify_dataset_integrity_only(REPO).research_train
_WF = load_walk_forward_protocol(REPO / WALK_FORWARD_PROTOCOL_RELPATH)


def _build() -> M3CProtocol:
    return build_m3c_protocol(
        research_train=_RESEARCH_TRAIN,
        wf_protocol=_WF,
        package_version="0.6.0",
        lineage_sha256="e" * 64,
        budget_sha256="f" * 64,
        frozen_m2_dossier_sha256="1" * 64,
        development_partition_sha256="2" * 64,
    )


def _reparse(protocol: M3CProtocol, **changes: object) -> M3CProtocol:
    payload = json.loads(protocol.to_json_bytes())
    payload.update(changes)
    return M3CProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestBuildAndRoundTrip:
    def test_round_trips_byte_stably(self) -> None:
        protocol = _build()
        raw = protocol.to_json_bytes()
        assert M3CProtocol.from_json_bytes(raw).to_json_bytes() == raw
        assert M3CProtocol.from_json_bytes(raw) == protocol

    def test_serialization_is_canonical(self) -> None:
        raw = _build().to_json_bytes()
        assert raw.endswith(b"\n")
        reencoded = (
            json.dumps(json.loads(raw), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        assert raw == reencoded

    def test_pins_the_experiment_shape(self) -> None:
        p = _build()
        assert p.candidate_id == M3C_CANDIDATE_ID
        assert p.candidate_fingerprint == CANDIDATE_FINGERPRINT
        assert p.strategies == M3C_STRATEGY_NAMES
        assert list(p.cost_scenarios) == list(_SCEN)
        assert p.permitted_data_level == "research_train"
        assert p.research_train_row_count == 2221
        assert p.initial_training_rows == 1095
        assert p.oos_fold_count == 5
        assert p.max_context_bars == M3C_MAX_CONTEXT_BARS == 252
        assert p.initial_cash == INITIAL_CASH == 10_000.0
        assert p.primary_scenario == "causal_proxy_base"
        assert p.primary_comparator == "buy_and_hold"
        assert p.primary_statistic == "mean_paired_daily_log_excess"
        assert p.bootstrap_algorithm == M3C_BOOTSTRAP_ALGORITHM
        assert p.bootstrap_seed == M3C_BOOTSTRAP_SEED == 20260714
        assert p.bootstrap_resamples == M3C_BOOTSTRAP_RESAMPLES == 20000
        assert p.bootstrap_confidence == M3C_BOOTSTRAP_CONFIDENCE == 0.95
        assert p.bootstrap_block_length_rule == "floor(n**(1/3))"
        assert p.decision_alpha == 0.05
        assert p.promotion_criteria == ("P1", "P2", "P3", "P4", "P5", "P6", "P7")

    def test_binds_empty_sealed_ledgers(self) -> None:
        p = _build()
        assert p.development_gate_ledger_sha256 == EMPTY_SHA256
        assert p.final_holdout_ledger_sha256 == EMPTY_SHA256

    def test_content_fingerprint_matches_walk_forward_protocol(self) -> None:
        assert _build().research_train_content_fingerprint == (
            _WF.research_train_content_fingerprint
        )

    def test_build_rejects_a_mismatched_research_train(self) -> None:
        with pytest.raises(ProtocolError, match="fingerprint"):
            build_m3c_protocol(
                research_train=_RESEARCH_TRAIN.iloc[:-1],
                wf_protocol=_WF,
                package_version="0.6.0",
                lineage_sha256="e" * 64,
                budget_sha256="f" * 64,
                frozen_m2_dossier_sha256="1" * 64,
                development_partition_sha256="2" * 64,
            )

    def test_load_round_trips(self, tmp_path: Path) -> None:
        protocol = _build()
        path = tmp_path / "protocol.json"
        path.write_bytes(protocol.to_json_bytes())
        assert load_m3c_protocol(str(path)) == protocol


class TestPinsRejectTampering:
    def test_reordered_strategies_are_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="strategies"):
            _reparse(_build(), strategies=list(reversed(M3C_STRATEGY_NAMES)))

    def test_reordered_cost_scenarios_are_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="cost scenarios"):
            _reparse(_build(), cost_scenarios=list(reversed(_SCEN)))

    def test_changed_initial_cash_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="initial_cash"):
            _reparse(_build(), initial_cash=5_000.0)

    def test_changed_boundary_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="initial_training_rows"):
            _reparse(_build(), initial_training_rows=1096)

    def test_changed_context_cap_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="max_context_bars"):
            _reparse(_build(), max_context_bars=55)

    def test_changed_candidate_fingerprint_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="candidate_fingerprint"):
            _reparse(_build(), candidate_fingerprint="0" * 64)

    def test_changed_bootstrap_seed_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="bootstrap_seed"):
            _reparse(_build(), bootstrap_seed=1)

    def test_changed_decision_alpha_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="decision_alpha"):
            _reparse(_build(), decision_alpha=0.1)

    def test_nonempty_sealed_ledger_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="ledger"):
            dataclasses.replace(_build(), development_gate_ledger_sha256="0" * 64)

    def test_wrong_experiment_id_is_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="experiment_id"):
            _reparse(_build(), experiment_id="m3c-dual-horizon-trend-v1-run-002")


class TestStrictParsing:
    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(_build().to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(_REJECT):
            M3CProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_missing_key_is_rejected(self) -> None:
        payload = json.loads(_build().to_json_bytes())
        del payload["candidate_fingerprint"]
        with pytest.raises(_REJECT):
            M3CProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_duplicate_key_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            M3CProtocol.from_json_bytes(b'{"decision_alpha": 0.05, "decision_alpha": 0.05}')

    def test_bool_as_int_is_rejected(self) -> None:
        payload = json.loads(_build().to_json_bytes())
        payload["oos_fold_count"] = True
        with pytest.raises(_REJECT):
            M3CProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))
