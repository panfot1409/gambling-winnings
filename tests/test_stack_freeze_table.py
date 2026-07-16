"""Immutable freeze-table verifier for the M3C-M3E stacked-acceptance audit.

``docs/M3C_M3E_STACK_FREEZE_TABLE.json`` snapshots the byte hash, length, mode, and
classification of every committed ``research/**`` artifact at the stacked head. This
test re-derives those hashes from the working tree and proves the table still binds —
a drift-detection **acceptance aid**, not a replacement for the canonical per-milestone
verifiers named in each row's ``verifier_authority`` (``verify_m3d_program``,
``m3c.verify_archive``, ``fractional.replay``, etc.), which remain the authorities.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
TABLE_PATH = REPO_ROOT / "docs/M3C_M3E_STACK_FREEZE_TABLE.json"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _table() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(TABLE_PATH.read_text())
    return doc


def test_freeze_table_covers_every_research_file() -> None:
    tracked = set(
        subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "ls-files", "research"], text=True
        ).split()
    )
    listed = {row["path"] for row in _table()["files"]}
    assert listed == tracked, f"table drift: missing={tracked - listed}, extra={listed - tracked}"


def test_every_frozen_artifact_still_matches_its_recorded_hash() -> None:
    mismatches: list[str] = []
    for row in _table()["files"]:
        data = (REPO_ROOT / row["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"] or len(data) != row["byte_length"]:
            mismatches.append(row["path"])
    assert not mismatches, f"freeze-table hash drift: {mismatches}"


def test_sealed_ledgers_are_classified_and_byte_empty() -> None:
    sealed = [r for r in _table()["files"] if r["classification"] == "append_only_sealed"]
    # exactly the three known access/evaluation ledgers
    assert {r["path"] for r in sealed} == {
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    }
    for r in sealed:
        assert r["byte_length"] == 0
        assert r["sha256"] == EMPTY_SHA
        assert (REPO_ROOT / r["path"]).read_bytes() == b""


def test_proposal_registry_is_append_chain_with_no_proposal() -> None:
    rows = [r for r in _table()["files"] if r["classification"] == "append_only_chain"]
    assert [r["path"] for r in rows] == ["research/m3e/proposal_registry.jsonl"]
    records = [
        json.loads(line)
        for line in (REPO_ROOT / rows[0]["path"]).read_text().splitlines()
        if line.strip()
    ]
    assert [rec.get("entry_kind") for rec in records] == ["genesis", "audit_noop"]
    assert not [rec for rec in records if rec.get("entry_kind") == "proposal"]


def test_table_references_canonical_verifier_authorities() -> None:
    # The table is an aid, not a competing provenance truth: every row names the
    # milestone verifier that is the real authority.
    for row in _table()["files"]:
        assert row["verifier_authority"], row["path"]
        assert row["classification"] in {
            "immutable",
            "append_only_sealed",
            "append_only_chain",
            "documentation",
        }
