"""Independent acceptance baseline — one reviewed fixture pinning run-001.

A single standing regression that freezes the exact bytes of the immutable run-001
record and its sealed context, so any future drift of a financial artifact, a
sealed ledger, or the registry lifecycle fails loudly. The digests are recorded
once here (the reviewed acceptance fixture); no other module duplicates them.
Read-only — it never re-runs the experiment or reads a sealed row.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import eth_research
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import M3B_REGISTRY_RELPATH, read_registry

REPO = Path(eth_research.__file__).resolve().parents[2]

# The frozen acceptance baseline (SHA-256 of the exact committed bytes).
_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
IMMUTABLE_BASELINE: dict[str, str] = {
    "research/m3b/experiment_registry.jsonl": (
        "204e66d21e41d0ca5af6620fd71af89ce561085a21b59a3e4786238bfa1e3eb9"
    ),
    "research/m3b/fractional_protocol.json": (
        "9c1e00eca5e8e58ce88e05d0b4ccdb71b34f798afe72cda3e9c88dee5641d4b6"
    ),
    "research/m3b/fractional_results.json": (
        "81f94fab60f4f168bf5bb237c1e32e0d4567f4325ee6c541af7feffca2ab9dfc"
    ),
    "research/m3b/fractional_report.md": (
        "68501639e7ba0660c7114c5b502861996b25bc0dff7e136500f4aca28260ae96"
    ),
    "research/m3b/experiments/run-001/manifest.json": (
        "d91ac46e58b8650da8e15fad19ec83520de0ada1989f0c5b16268e91fe82ca36"
    ),
}
SEALED_LEDGERS: tuple[str, ...] = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
)


def _sha256(relpath: str) -> str:
    return hashlib.sha256((REPO / relpath).read_bytes()).hexdigest()


def test_immutable_run001_artifacts_have_their_frozen_digests() -> None:
    for relpath, expected in IMMUTABLE_BASELINE.items():
        assert _sha256(relpath) == expected, relpath


def test_both_sealed_ledgers_are_byte_empty() -> None:
    for ledger in SEALED_LEDGERS:
        assert (REPO / ledger).stat().st_size == 0, ledger
        assert _sha256(ledger) == _EMPTY, ledger


def test_registry_carries_exactly_the_run001_lifecycle() -> None:
    events = read_registry(REPO / M3B_REGISTRY_RELPATH)
    assert [e.event for e in events] == ["registered", "started", "completed"]
    assert {e.experiment_id for e in events} == {RUN_001_EXPERIMENT_ID}


def test_the_75_cell_grid_identity_is_exact() -> None:
    from eth_research.fractional.results import load_fractional_results

    results = load_fractional_results(str(REPO / "research/m3b/fractional_results.json"))
    grid = {(c.strategy, c.cost_scenario, c.fold_index) for c in results.fold_cells}
    assert len(results.fold_cells) == 75
    assert len(grid) == 75  # no duplicate cell
    assert len({c.strategy for c in results.fold_cells}) == 5
    assert len({c.cost_scenario for c in results.fold_cells}) == 3
    assert len({c.fold_index for c in results.fold_cells}) == 5
