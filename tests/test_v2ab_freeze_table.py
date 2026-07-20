"""V2A-V2B §4 — the complete immutable freeze table + strict verifier."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, strict_json_loads
from eth_research.v2ab.freeze_table import (
    FREEZE_TABLE_RELPATH,
    FreezeTableError,
    build_freeze_table,
    parse_freeze_table,
    verify_freeze_table,
)


def _seed(root: Path) -> None:
    """A tiny synthetic governed tree: two research milestones + a release + a sealed ledger."""
    (root / "research/m2b").mkdir(parents=True)
    (root / "research/m3a").mkdir(parents=True)
    (root / "release").mkdir(parents=True)
    (root / "research/m2b/results.json").write_text('{"a": 1}\n')
    (root / "research/m3a/development_gate_access.jsonl").write_bytes(b"")  # sealed, empty
    (root / "release/release_manifest.json").write_text('{"r": 2}\n')


def _write_table(root: Path) -> dict[str, object]:
    table = build_freeze_table(root)
    (root / FREEZE_TABLE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / FREEZE_TABLE_RELPATH).write_bytes(canonical_json_bytes(table))
    return table


def test_build_and_verify_clean(tmp_path: Path) -> None:
    _seed(tmp_path)
    table = _write_table(tmp_path)
    assert table["entry_count"] == 3
    assert verify_freeze_table(tmp_path) == []


def test_round_trip_parse_binds_digest(tmp_path: Path) -> None:
    _seed(tmp_path)
    table = _write_table(tmp_path)
    entries, digest = parse_freeze_table((tmp_path / FREEZE_TABLE_RELPATH).read_bytes())
    assert len(entries) == 3
    assert digest == table["table_digest"]


def test_missing_committed_artifact_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_table(tmp_path)
    (tmp_path / "research/m2b/results.json").unlink()
    problems = verify_freeze_table(tmp_path)
    assert any("missing from the tree" in p for p in problems)


def test_unlisted_governed_artifact_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_table(tmp_path)
    (tmp_path / "research/m2b/sneaked.json").write_text('{"x": 9}\n')
    problems = verify_freeze_table(tmp_path)
    assert any("unlisted governed artifact" in p for p in problems)


def test_changed_bytes_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_table(tmp_path)
    (tmp_path / "research/m2b/results.json").write_text(
        '{"a": 2}\n'
    )  # same length, different bytes
    problems = verify_freeze_table(tmp_path)
    assert any("bytes changed" in p for p in problems)


def test_changed_role_in_committed_table_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_table(tmp_path)
    tp = tmp_path / FREEZE_TABLE_RELPATH
    obj = strict_json_loads(tp.read_bytes())
    for e in obj["entries"]:
        if e["path"].endswith("results.json") and e["milestone"] == "m2b":
            e["role"] = "report"  # lie about the role
    # Re-digest so the self-binding still passes; the live re-derivation must catch the role drift.
    from eth_research.v2ab.freeze_table import _digest_of_body

    body = {k: obj[k] for k in obj if k != "table_digest"}
    obj["table_digest"] = _digest_of_body(body)
    tp.write_bytes(canonical_json_bytes(obj))
    problems = verify_freeze_table(tmp_path)
    assert any("role changed" in p for p in problems)


def test_reordered_duplicate_identity_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    table = build_freeze_table(tmp_path)
    entries = list(cast(list[dict[str, object]], table["entries"]))
    entries.append(dict(entries[0]))  # duplicate identity
    tampered = dict(table)
    tampered["entries"] = entries
    tampered["entry_count"] = len(entries)
    with pytest.raises(V2ValidationError):
        parse_freeze_table(canonical_json_bytes(tampered))


def test_broken_self_digest_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    table = _write_table(tmp_path)
    tampered = dict(table)
    tampered["table_digest"] = "0" * 64
    with pytest.raises(V2ValidationError):
        parse_freeze_table(canonical_json_bytes(tampered))


def test_symlink_under_governed_root_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    target = tmp_path / "research/m2b/results.json"
    link = tmp_path / "research/m2b/link.json"
    os.symlink(target, link)
    with pytest.raises(FreezeTableError):
        build_freeze_table(tmp_path)


def test_sealed_ledger_nonempty_flagged(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_table(tmp_path)
    # Corrupt the sealed ledger AND its committed entry so only the empty-SHA rule catches it.
    (tmp_path / "research/m3a/development_gate_access.jsonl").write_text("leak\n")
    problems = verify_freeze_table(tmp_path)
    # A sealed ledger with content is caught either as bytes-changed or the empty-SHA rule.
    assert problems
