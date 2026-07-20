"""V2C section 33: the append-only, hash-chained operational-qualification registry.

Covers the chained lifecycle (registered -> qualified), the one-shot budget per protocol, the
fail-closed chain/hash re-verification on read, and the committed byte-empty genesis ledger.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.v2c.oq.registry import (
    OQ_EVENT_QUALIFIED,
    OQ_EVENT_REGISTERED,
    OQ_REGISTRY_PATH,
    OQRegistryError,
    append_oq_event,
    read_oq_registry,
    verify_oq_registry,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_DIGEST = "a" * 64


def _register(path: Path, protocol_id: str = "oq_cash_control") -> None:
    append_oq_event(
        path,
        event=OQ_EVENT_REGISTERED,
        protocol_id=protocol_id,
        package_version="2.0.0.dev2",
        payload={
            "fixture_digest": _DIGEST,
            "fault_schedule_digest": _DIGEST,
            "criteria_digest": _DIGEST,
        },
    )


def _qualify(path: Path, protocol_id: str = "oq_cash_control", *, qualified: bool = True) -> None:
    append_oq_event(
        path,
        event=OQ_EVENT_QUALIFIED,
        protocol_id=protocol_id,
        package_version="2.0.0.dev2",
        payload={"qualified": qualified, "result_digest": _DIGEST},
    )


def test_empty_ledger_is_clean(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    ledger.touch()
    assert read_oq_registry(ledger) == ()
    assert verify_oq_registry(ledger) == []


def test_register_then_qualify_chains(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    _register(ledger)
    _qualify(ledger)
    events = read_oq_registry(ledger)
    assert [e.event for e in events] == [OQ_EVENT_REGISTERED, OQ_EVENT_QUALIFIED]
    assert [e.seq for e in events] == [0, 1]
    assert events[1].prev_hash == events[0].entry_hash
    assert verify_oq_registry(ledger) == []


def test_one_shot_budget_rejects_double_registration(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    _register(ledger)
    with pytest.raises(OQRegistryError, match="one-shot"):
        _register(ledger)


def test_one_shot_budget_rejects_double_qualification(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    _register(ledger)
    _qualify(ledger)
    with pytest.raises(OQRegistryError, match="one-shot"):
        _qualify(ledger)


def test_qualify_requires_prior_registration(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    with pytest.raises(OQRegistryError, match="no prior registration"):
        _qualify(ledger)


def test_tampered_entry_hash_fails_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "oq.jsonl"
    _register(ledger)
    corrupted = ledger.read_bytes().replace(
        b'"package_version":"2.0.0.dev2"', b'"package_version":"9.9.9"'
    )
    ledger.write_bytes(corrupted)
    assert verify_oq_registry(ledger)  # non-empty problem list
    with pytest.raises(OQRegistryError):
        read_oq_registry(ledger)


def test_committed_genesis_ledger_is_byte_empty_and_clean() -> None:
    ledger = REPO_ROOT / OQ_REGISTRY_PATH
    assert ledger.is_file()
    assert ledger.stat().st_size == 0
    assert verify_oq_registry(ledger) == []
