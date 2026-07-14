"""Acceptance-audit reproduction: the protocol parser must decode, not repair.

Independent acceptance finding A1 (Class B): ``FractionalProtocol.from_json_bytes``
and ``_scenario_from_dict`` coerced parsed JSON via ``int()/float()/str()/bool()``,
so a numeric-string ``initial_cash``/tolerance/fee_rate, a ``bool`` schema version,
or a ``float`` row count were *repaired* into the target type and accepted — the
R4 strict-parse contract the closure established for the results parser was never
applied to the protocol parser. Parsing must only decode and delegate to the same
invariant surface as direct construction; no value repair is allowed.

The committed run-001 protocol has correct types, so it still parses and
re-serializes byte-identically (asserted here) — the fix rejects malformed input
only and changes no financial byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.protocol import (
    FRACTIONAL_PROTOCOL_RELPATH,
    FractionalProtocol,
)

REPO = Path(eth_research.__file__).resolve().parents[2]
_RAW = (REPO / FRACTIONAL_PROTOCOL_RELPATH).read_bytes()
_REJECT = (ValueError, TypeError)


def _mutated(**overrides: object) -> bytes:
    payload = json.loads(_RAW)
    payload.update(overrides)
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _mutated_scenario(index: int, **overrides: object) -> bytes:
    payload = json.loads(_RAW)
    payload["cost_scenarios"][index].update(overrides)
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def test_committed_protocol_round_trips_byte_identically() -> None:
    assert FractionalProtocol.from_json_bytes(_RAW).to_json_bytes() == _RAW


def test_numeric_string_initial_cash_is_rejected() -> None:
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated(initial_cash="10000.0"))


def test_numeric_string_tolerance_is_rejected() -> None:
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated(cash_tolerance="1e-06"))


def test_bool_schema_version_is_rejected() -> None:
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated(fractional_protocol_schema_version=True))


def test_float_row_count_is_rejected() -> None:
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated(research_train_row_count=2221.0))


def test_bool_drawdown_flag_string_is_rejected() -> None:
    # bool("false") == True previously flipped the flag; a string must be rejected.
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated(drawdown_breaker_enabled="false"))


def test_numeric_string_scenario_rate_is_rejected() -> None:
    with pytest.raises(_REJECT):
        FractionalProtocol.from_json_bytes(_mutated_scenario(0, fee_rate="0.001"))
