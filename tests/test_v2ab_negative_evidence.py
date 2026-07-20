"""Adversarial tests for the append-only, hash-chained negative-evidence index.

Confirms the committed index reproduces and verifies, and that every enumerated tamper is refused:
an omitted or duplicated family, a changed decision or endpoint, a removed cost scenario, a softened
limitation, fabricated sealed access, a removed sealed-access disclosure, a reordered or deleted
line, a broken previous-line digest, and an unknown status.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.v2ab import negative_evidence as ne

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _clone(tmp_path: Path) -> Path:
    dst = tmp_path / "repo"
    shutil.copytree(_REPO_ROOT / "research", dst / "research")
    return dst


def _records() -> list[dict[str, object]]:
    return ne.negative_evidence_ledger_records(_REPO_ROOT)


def _rechain(records: list[dict[str, object]]) -> bytes:
    return render_ledger_bytes(chained_line_bytes(records))


def _write(root: Path, data: bytes) -> None:
    (root / ne.NEGATIVE_EVIDENCE_RELPATH).write_bytes(data)


def _mutate(records: list[dict[str, object]], family_id: str, key: str, value: object) -> None:
    for record in records:
        if record.get("family_id") == family_id:
            record[key] = value
            return
    raise AssertionError(f"no record for family {family_id!r}")


# --------------------------------------------------------------------------- #
# clean-state guarantees                                                       #
# --------------------------------------------------------------------------- #
def test_verify_is_clean_on_committed_tree() -> None:
    assert ne.verify_negative_evidence(_REPO_ROOT) == []


def test_index_is_genesis_plus_twelve_records() -> None:
    raw, records = load_and_verify_chain(_REPO_ROOT, ne.NEGATIVE_EVIDENCE_RELPATH)
    assert raw != b""
    assert records[0]["kind"] == "negative_evidence_genesis"
    body = records[1:]
    assert len(body) == 12
    assert all(r["kind"] == "negative_evidence_record" for r in body)


def test_status_distribution_preserves_exact_decision_semantics() -> None:
    assert ne.negative_evidence_status_distribution(_REPO_ROOT) == {
        "benchmark_only": 2,
        "no_nomination": 2,
        "not_eligible": 2,
        "rejected_for_promotion": 4,
        "risk_reduction_observation": 2,
    }


def test_every_status_is_in_the_closed_set_and_no_sealed_access() -> None:
    for record in ne.build_negative_evidence_index(_REPO_ROOT):
        assert record.status in ne.NEGATIVE_EVIDENCE_STATUSES
        assert record.sealed_data_touched is False
        assert "sealed" in record.sealed_access_disclosure.lower()


# --------------------------------------------------------------------------- #
# adversarial matrix (each tamper must be refused)                             #
# --------------------------------------------------------------------------- #
def test_omitted_family_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _write(root, _rechain(records[:-1]))  # drop the last body record (chain stays valid)
    assert any("omitted" in p for p in ne.verify_negative_evidence(root))


def test_duplicated_family_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    records.append(copy.deepcopy(records[1]))
    _write(root, _rechain(records))
    assert any("duplicated" in p for p in ne.verify_negative_evidence(root))


def test_changed_decision_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(records, "m3c_dual_horizon_trend_63_252_vol_target_30d_50pct", "decision", "promoted")
    _write(root, _rechain(records))
    assert any("decision" in p for p in ne.verify_negative_evidence(root))


def test_changed_endpoint_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(records, "v2a_meanrev_zscore_accumulation", "primary_endpoint", "sharpe_ratio")
    _write(root, _rechain(records))
    assert any("primary_endpoint" in p for p in ne.verify_negative_evidence(root))


def test_removed_cost_scenario_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(records, "m3a_donchian_breakout", "cost_scenarios", ["base", "stressed"])
    _write(root, _rechain(records))
    assert any("cost scenario" in p for p in ne.verify_negative_evidence(root))


def test_softened_limitation_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(
        records,
        "m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
        "limitations",
        ["This candidate is basically fine and nearly cleared every gate."],
    )
    _write(root, _rechain(records))
    assert any("limitation" in p for p in ne.verify_negative_evidence(root))


def test_fabricated_sealed_access_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(records, "v2b_cross_asset_btc_confirmed_eth_trend", "sealed_data_touched", True)
    _write(root, _rechain(records))
    assert any("fabricated sealed access" in p for p in ne.verify_negative_evidence(root))


def test_removed_sealed_access_disclosure_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    for record in records:
        if record.get("family_id") == "m3b_vol_target_buy_and_hold_30d_50pct":
            del record["sealed_access_disclosure"]
    _write(root, _rechain(records))
    assert any("disclosure" in p for p in ne.verify_negative_evidence(root))


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    records = _records()
    _mutate(records, "m3a_sma_crossover", "status", "quietly_promotable")
    _write(root, _rechain(records))
    assert any("unknown status" in p for p in ne.verify_negative_evidence(root))


def test_reordered_line_breaks_the_chain(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    lines = _rechain(_records()).rstrip(b"\n").split(b"\n")
    lines[1], lines[2] = lines[2], lines[1]
    _write(root, b"\n".join(lines) + b"\n")
    assert any("hash chain invalid" in p for p in ne.verify_negative_evidence(root))


def test_deleted_line_breaks_the_chain(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    lines = _rechain(_records()).rstrip(b"\n").split(b"\n")
    del lines[2]
    _write(root, b"\n".join(lines) + b"\n")
    assert any("hash chain invalid" in p for p in ne.verify_negative_evidence(root))


def test_broken_previous_digest_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    raw = _rechain(_records())
    tampered = raw.replace(
        b"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", b"0" * 64, 1
    )
    assert tampered != raw
    _write(root, tampered)
    assert any("hash chain invalid" in p for p in ne.verify_negative_evidence(root))
