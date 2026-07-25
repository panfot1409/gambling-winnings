"""The invariant catalog must be well-formed, and honest about what it covers.

Two different things are checked here, and they are not interchangeable:

* the catalog's own shape — an invariant with no enforcement is not one, and an
  invariant enforced by fewer than all three paths must say why;
* the catalog's coverage claims against **measured** behaviour — the committed
  probe truth table records, for 43 coordinated attacks, which enforcement paths
  actually refused. If a path accepted an attack aimed at an invariant that the
  catalog says that path enforces, the catalog is overstating its coverage. That
  is the failure this file exists to make loud.

The second check is the reason the truth table is committed rather than kept as a
one-off transcript: a coverage claim nobody can re-derive is a claim nobody can
falsify.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from eth_research.m3e.invariant_catalog import (
    ALL_PATHS,
    BY_ID,
    CATALOG,
    PATH_COMPATIBILITY,
    PATH_INDEPENDENT,
    PATH_PRODUCTION,
    Invariant,
    as_json,
    coverage_gaps,
    invariants_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRUTH_TABLE = REPO_ROOT / "docs/V2E_ACCEPTANCE_PROBE_TRUTH_TABLE.json"

#: Truth-table reader name -> catalog enforcement path. ``public_entry`` is the
#: production verifier's CLI, not a fourth implementation, so it maps to the same
#: path and is not double-counted.
READER_TO_PATH = {
    "production": PATH_PRODUCTION,
    "m3f": PATH_COMPATIBILITY,
    "stdlib": PATH_INDEPENDENT,
}

_INVARIANT_ID = re.compile(r"\b([A-Z]{3,5}-[0-9]{2})\b")


def _truth_table() -> dict[str, Any]:
    if not TRUTH_TABLE.is_file():
        pytest.skip(f"{TRUTH_TABLE.name} is not committed in this tree")
    payload = json.loads(TRUTH_TABLE.read_text())
    assert isinstance(payload, dict)
    return payload


# --- shape -----------------------------------------------------------------


def test_every_invariant_states_at_least_one_enforcement_path() -> None:
    for inv in CATALOG:
        assert inv.paths, f"{inv.invariant_id} claims no enforcement"
        assert set(inv.paths) <= set(ALL_PATHS)


def test_partial_coverage_must_state_its_gap() -> None:
    for inv in CATALOG:
        if len(inv.paths) < len(ALL_PATHS):
            assert inv.gap, f"{inv.invariant_id} is partial but does not say why"
        else:
            assert not inv.gap, f"{inv.invariant_id} is fully covered but declares a gap"


def test_full_coverage_cannot_also_declare_a_gap() -> None:
    with pytest.raises(ValueError, match="full coverage cannot also declare a gap"):
        Invariant("X-01", "statement", ALL_PATHS, gap="unnecessary")


def test_an_invariant_with_no_enforcement_is_rejected() -> None:
    with pytest.raises(ValueError, match="an invariant with no enforcement is not one"):
        Invariant("X-02", "statement", ())


def test_invariant_ids_are_unique_and_indexed() -> None:
    ids = [inv.invariant_id for inv in CATALOG]
    assert len(ids) == len(set(ids))
    assert set(BY_ID) == set(ids)


def test_json_rendering_agrees_with_the_catalog() -> None:
    payload = as_json()
    assert payload["invariant_count"] == len(CATALOG)
    assert payload["fully_covered_count"] == len(CATALOG) - len(coverage_gaps())
    rendered = payload["invariants"]
    assert isinstance(rendered, list)
    assert [dict(i)["invariant_id"] for i in rendered] == [inv.invariant_id for inv in CATALOG]


def test_every_path_enforces_something() -> None:
    for path in ALL_PATHS:
        assert invariants_for(path), f"{path} enforces nothing"


# --- coverage claims vs measured behaviour ---------------------------------


def test_the_truth_table_measures_the_current_catalog() -> None:
    """Every invariant a probe names must exist, so a rename cannot silently
    orphan a row and make the comparison below vacuous."""
    table = _truth_table()
    for row in table["rows"]:
        for invariant_id in _INVARIANT_ID.findall(row["intended_invariant"]):
            if invariant_id.startswith("GEN-") or invariant_id.startswith("M3F-"):
                continue  # genealogy codes and M3F-layer artifacts are catalogued elsewhere
            assert invariant_id in BY_ID, (
                f"probe {row['probe_id']} names {invariant_id}, which is not in the catalog"
            )


def test_no_path_accepts_an_attack_on_an_invariant_it_claims_to_enforce() -> None:
    """The catalog must not claim coverage the probe matrix contradicts.

    This is the check that fails when a required invariant is absent from an
    applicable path: if the stdlib reader accepted an attack aimed at DATA-03 and
    the catalog said DATA-03 was enforced on the independent path, the claim is
    false and this test says so, naming the probe that proves it.
    """
    table = _truth_table()
    overstated: list[str] = []
    for row in table["rows"]:
        if row["family"] == "control":
            continue
        named = [i for i in _INVARIANT_ID.findall(row["intended_invariant"]) if i in BY_ID]
        if not named:
            continue
        for reader, path in READER_TO_PATH.items():
            if row["results"][reader]["exit"] != 0:
                continue  # this path refused; nothing to contradict
            for invariant_id in named:
                if path in BY_ID[invariant_id].paths:
                    overstated.append(
                        f"{invariant_id} claims the {path!r} path, but probe "
                        f"{row['probe_id']} ({row['mutation']}) was ACCEPTED there"
                    )
    assert not overstated, "catalog overstates coverage:\n  " + "\n  ".join(overstated)


def test_the_recorded_controls_all_passed() -> None:
    """A truth table whose controls failed cannot support any claim above."""
    table = _truth_table()
    assert table["totals"]["controls"] >= 5
    assert table["totals"]["controls_passed"] == table["totals"]["controls"]


def test_no_attack_in_the_truth_table_was_accepted_everywhere() -> None:
    table = _truth_table()
    assert table["totals"]["accepted_by_all_readers"] == 0, (
        "an attack accepted by every reader is a hole, not a coverage gap"
    )
