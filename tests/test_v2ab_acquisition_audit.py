"""Adversarial + clean tests for the independent BTC-acquisition acceptance audit.

Every adversarial test mutates a *copy* of the committed evidence under ``tmp_path`` and
points the audit at that copy, so no accepted artifact is ever touched. The clean tests run
against the real repository and must report zero problems.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eth_research.v2ab.acquisition_audit import (
    ACCEPTED_BTC_DATASET_FINGERPRINT,
    EXPECTED_ROW_COUNT,
    audit_btc_acquisition,
    verify_btc_acquisition,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GENESIS = "coinbase-btc-usd-research-genesis-001"
AUDIT = "coinbase-btc-usd-research-audit-002"


def _copy_evidence(tmp_path: Path) -> Path:
    """Copy the exact evidence the audit reads into a throwaway repo root."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "research/v2b", root / "research/v2b")
    shutil.copytree(REPO_ROOT / ".github/workflows", root / ".github/workflows")
    (root / "docs").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "docs/V2B_ACQUISITION.md", root / "docs/V2B_ACQUISITION.md")
    # The copied workflow set includes the V2D update workflow, whose narrow
    # contents: write allowance is valid only alongside the committed activation anchor.
    (root / "governance/v2d").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "governance/v2d/prospective_activation.json",
        root / "governance/v2d/prospective_activation.json",
    )
    return root


def _raw(root: Path, attempt: str) -> Path:
    return root / "research/v2b/raw/coinbase" / attempt


def _perturb_body(path: Path) -> bytes:
    """Change one candle's close price (identity-preserving) so the fingerprint shifts."""
    rows = json.loads(path.read_bytes())
    for row in rows:
        if row[4] != row[3]:  # close != open; close := open keeps low <= close <= high
            row[4] = row[3]
            break
    data = json.dumps(rows, separators=(",", ":")).encode()
    path.write_bytes(data)
    return data


def _sync_receipt_window(receipt_path: Path, ordinal: int, new_body: bytes) -> None:
    obj = json.loads(receipt_path.read_bytes())
    window = obj["windows"][ordinal]
    window["body_sha256"] = hashlib.sha256(new_body).hexdigest()
    window["body_bytes"] = len(new_body)
    receipt_path.write_bytes(json.dumps(obj).encode())


# --------------------------------------------------------------------------- #
# clean                                                                         #
# --------------------------------------------------------------------------- #
def test_real_repo_verifies_clean() -> None:
    assert verify_btc_acquisition(REPO_ROOT) == []


def test_audit_reports_independently_derived_facts() -> None:
    a = audit_btc_acquisition(REPO_ROOT)
    assert a.ok
    assert a.row_count == EXPECTED_ROW_COUNT == 2221
    assert a.first_open == "2016-05-23T00:00:00Z"
    assert a.last_open == "2022-06-21T00:00:00Z"
    # genesis == audit == committed joint == accepted anchor.
    assert (
        a.genesis_fingerprint
        == a.audit_fingerprint
        == a.committed_btc_dataset_fingerprint
        == ACCEPTED_BTC_DATASET_FINGERPRINT
    )
    assert a.canonical_candles_identical
    assert a.distinct_workflow_run_ids
    assert a.distinct_source_commits
    assert a.genesis_workflow_run_id != a.audit_workflow_run_id
    assert a.no_row_at_or_after_cutoff
    assert a.strict_monotonic_daily
    assert a.final_tree_acquisition_workflow_absent
    assert a.historical_acquisition_attested


def test_copied_evidence_verifies_clean(tmp_path: Path) -> None:
    assert verify_btc_acquisition(_copy_evidence(tmp_path)) == []


# --------------------------------------------------------------------------- #
# adversarial                                                                   #
# --------------------------------------------------------------------------- #
def test_copied_authorization_breaks_independence(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    # A forger copies genesis's single-use provenance identity onto the audit receipt so both
    # attempts share a workflow_run_id + source_commit: independence must break.
    genesis = json.loads((_raw(root, GENESIS) / "acquisition_receipt.json").read_bytes())
    audit_receipt = _raw(root, AUDIT) / "acquisition_receipt.json"
    obj = json.loads(audit_receipt.read_bytes())
    obj["workflow_run_id"] = genesis["workflow_run_id"]
    obj["source_commit"] = genesis["source_commit"]
    audit_receipt.write_bytes(json.dumps(obj).encode())
    a = audit_btc_acquisition(root)
    assert not a.ok
    assert not a.distinct_workflow_run_ids
    assert not a.distinct_source_commits
    assert any("independent" in p for p in a.problems)


def test_changed_plan_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    plan_path = root / "research/v2b/btc/acquisition_plan.json"
    obj = json.loads(plan_path.read_bytes())
    obj["max_buckets_per_request"] = 250  # a different plan than the immutable one
    plan_path.write_bytes(json.dumps(obj).encode())
    assert verify_btc_acquisition(root) != []


def test_extra_raw_file_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    (_raw(root, GENESIS) / "candles_099.json").write_bytes(b"[]")
    problems = verify_btc_acquisition(root)
    assert any("file set mismatch" in p for p in problems)


def test_removed_response_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    (_raw(root, AUDIT) / "candles_003.json").unlink()
    assert verify_btc_acquisition(root) != []


def test_changed_receipt_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    receipt = _raw(root, GENESIS) / "acquisition_receipt.json"
    obj = json.loads(receipt.read_bytes())
    obj["windows"][0]["body_sha256"] = "00" * 32  # a wrong-but-valid 64-hex digest
    receipt.write_bytes(json.dumps(obj).encode())
    assert verify_btc_acquisition(root) != []


def test_candle_row_moved_past_cutoff_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    body = _raw(root, GENESIS) / "candles_007.json"
    rows = json.loads(body.read_bytes())
    rows[0][0] = 1655856000  # 2022-06-22T00:00:00Z: at the sealed cutoff, must be rejected
    body.write_bytes(json.dumps(rows, separators=(",", ":")).encode())
    problems = verify_btc_acquisition(root)
    assert problems != []


def test_replaced_raw_body_and_local_receipt_still_caught(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    new_body = _perturb_body(_raw(root, GENESIS) / "candles_000.json")
    _sync_receipt_window(_raw(root, GENESIS) / "acquisition_receipt.json", 0, new_body)
    a = audit_btc_acquisition(root)
    assert not a.ok
    # Genesis now reproduces its own (updated) receipt, but no longer matches audit.
    assert not a.canonical_candles_identical


def test_replaced_both_attempts_consistently_still_caught(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    for attempt in (GENESIS, AUDIT):
        new_body = _perturb_body(_raw(root, attempt) / "candles_000.json")
        _sync_receipt_window(_raw(root, attempt) / "acquisition_receipt.json", 0, new_body)
    a = audit_btc_acquisition(root)
    assert not a.ok
    # The committed joint fingerprint + the hard-coded anchor are the un-forgeable checks.
    assert any("anchor" in p for p in a.problems)


def test_changed_dataset_lock_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    lock_path = root / "research/v2b/btc/dataset_lock.json"
    obj = json.loads(lock_path.read_bytes())
    obj["row_count"] = 2220
    lock_path.write_bytes(json.dumps(obj).encode())
    assert verify_btc_acquisition(root) != []


def test_symlinked_raw_root_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    coinbase = root / "research/v2b/raw/coinbase"
    moved = root / "research/v2b/raw/coinbase_real"
    coinbase.rename(moved)
    coinbase.symlink_to(moved, target_is_directory=True)
    problems = verify_btc_acquisition(root)
    assert any("symlink" in p for p in problems)


def test_path_traversal_symlink_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"[]")
    target = _raw(root, GENESIS) / "candles_003.json"
    target.unlink()
    target.symlink_to(outside)  # points outside the repository root
    problems = verify_btc_acquisition(root)
    assert any("symlink" in p or "escape" in p for p in problems)


def test_duplicate_raw_filename_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    src = _raw(root, GENESIS) / "candles_000.json"
    shutil.copy2(src, _raw(root, GENESIS) / "candles_000_copy.json")
    problems = verify_btc_acquisition(root)
    assert any("file set mismatch" in p for p in problems)


def test_reintroduced_acquire_workflow_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    wf = root / ".github/workflows/v2b-acquire.yml"
    wf.write_text(
        "name: acquire\n"
        "permissions:\n  contents: write\n"
        "jobs:\n  acquire:\n    steps:\n"
        "      - run: curl https://api.exchange.coinbase.com/products/BTC-USD/candles\n",
        encoding="utf-8",
    )
    a = audit_btc_acquisition(root)
    assert not a.final_tree_acquisition_workflow_absent
    assert any(
        "Coinbase" in p or "contents: write" in p or "acquisition workflow" in p for p in a.problems
    )


def test_present_acquisition_sentinel_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    (root / "research/v2b/acquire.trigger").write_text("go\n", encoding="utf-8")
    problems = verify_btc_acquisition(root)
    assert any("sentinel" in p for p in problems)


def test_v2d_write_allowance_does_not_generalize(tmp_path: Path) -> None:
    """Only the anchored V2D update workflow may carry ``contents: write``.

    An impostor basename with the same grant is still flagged, and deleting the
    committed V2D activation anchor fails the allowance closed for the real
    basename too.
    """
    root = _copy_evidence(tmp_path)
    rogue = root / ".github/workflows/rogue-with-write.yml"
    rogue.write_text(
        "name: rogue\non: workflow_dispatch\njobs:\n  j:\n    permissions:\n"
        "      contents: write\n    runs-on: ubuntu-latest\n    steps:\n      - run: 'true'\n",
        encoding="utf-8",
    )
    assert any(
        "rogue-with-write.yml grants contents: write" in p for p in verify_btc_acquisition(root)
    )
    rogue.unlink()
    assert verify_btc_acquisition(root) == []
    (root / "governance/v2d/prospective_activation.json").unlink()
    assert any(
        "m3e-prospective-update.yml grants contents: write" in p
        for p in verify_btc_acquisition(root)
    )


def test_dishonest_governance_amendment_rejected(tmp_path: Path) -> None:
    root = _copy_evidence(tmp_path)
    # Rewrite the amendment to erase the historical workflow (claim it never existed).
    (root / "docs/V2B_ACQUISITION.md").write_text(
        "# BTC acquisition\n\nThe data was always present. No workflow was ever involved.\n",
        encoding="utf-8",
    )
    problems = verify_btc_acquisition(root)
    assert any("historical" in p for p in problems)


@pytest.mark.parametrize("attempt", [GENESIS, AUDIT])
def test_missing_attempt_directory_rejected(tmp_path: Path, attempt: str) -> None:
    root = _copy_evidence(tmp_path)
    shutil.rmtree(_raw(root, attempt))
    assert verify_btc_acquisition(root) != []
