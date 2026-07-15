"""Tests for the M3D data-use ledger and sealed-partition firewall."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eth_research.m3d import chain
from eth_research.m3d.data_use import (
    LEDGER_PATH,
    build_data_use_ledger_bytes,
    verify_research_data_use,
)

_REPO = Path(__file__).resolve().parents[1]


def _records_without_previous() -> list[dict[str, Any]]:
    raw = (_REPO / LEDGER_PATH).read_bytes()
    records = chain.verify_chain(chain.split_ledger_lines(raw))
    out: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        copy.pop(chain.PREVIOUS_FIELD)
        out.append(copy)
    return out


def _write_rebuilt(records: list[dict[str, Any]]) -> None:
    (_REPO / LEDGER_PATH).write_bytes(chain.render_ledger_bytes(chain.chained_line_bytes(records)))


def test_build_is_deterministic_and_committed_matches() -> None:
    a = build_data_use_ledger_bytes(_REPO)
    b = build_data_use_ledger_bytes(_REPO)
    assert a == b
    assert (_REPO / LEDGER_PATH).read_bytes() == a
    verify_research_data_use(_REPO)


def test_sealed_partitions_have_zero_access() -> None:
    records = verify_research_data_use(_REPO)
    sealed = {r["partition"]: r for r in records if r.get("use_type") == "sealed_untouched"}
    assert set(sealed) == {"development_gate", "final_holdout"}
    for entry in sealed.values():
        assert entry["signals_computed"] is False
        assert entry["pnl_computed"] is False
        assert entry["metrics_computed"] is False
        assert entry["access_ledger_event_count"] == 0


def test_used_partitions_declare_real_use() -> None:
    records = verify_research_data_use(_REPO)
    used = [r for r in records if r.get("partition") in {"m2b_train", "research_train"}]
    assert used
    assert all(r["metrics_computed"] is True for r in used)


def test_firewall_rejects_sealed_partition_claiming_use() -> None:
    records = _records_without_previous()
    for record in records:
        if record.get("partition") == "development_gate":
            record["signals_computed"] = True
    original = (_REPO / LEDGER_PATH).read_bytes()
    try:
        _write_rebuilt(records)
        with pytest.raises(ValueError, match="must not declare any use"):
            verify_research_data_use(_REPO)
    finally:
        (_REPO / LEDGER_PATH).write_bytes(original)


def test_firewall_rejects_used_partition_claiming_unused() -> None:
    records = _records_without_previous()
    for record in records:
        if record.get("partition") == "research_train" and record.get("milestone") == "m3c":
            record["metrics_computed"] = False
    original = (_REPO / LEDGER_PATH).read_bytes()
    try:
        _write_rebuilt(records)
        with pytest.raises(ValueError, match="must declare a real use"):
            verify_research_data_use(_REPO)
    finally:
        (_REPO / LEDGER_PATH).write_bytes(original)


def test_verify_rejects_value_tamper() -> None:
    records = _records_without_previous()
    for record in records:
        if record.get("partition") == "m2b_train":
            record["row_count"] = 999999
    original = (_REPO / LEDGER_PATH).read_bytes()
    try:
        _write_rebuilt(records)
        with pytest.raises(ValueError, match="does not match the rebuilt"):
            verify_research_data_use(_REPO)
    finally:
        (_REPO / LEDGER_PATH).write_bytes(original)
