"""The aligned ETH/BTC joint partition: identity, alignment, firewall, substitution resistance."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.v2b import partition as jp
from eth_research.v2b.acquisition import RESEARCH_CUTOFF_LAST_OPEN, WINDOW_END_EXCLUSIVE

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_committed_identity_reproduces() -> None:
    jp.verify_joint_partition(REPO_ROOT)
    committed = (REPO_ROOT / jp.JOINT_PARTITION_IDENTITY_RELPATH).read_bytes()
    assert committed == jp.render_partition_identity_bytes(REPO_ROOT)


def test_panel_shape_alignment_and_firewall() -> None:
    part = jp.build_joint_partition(REPO_ROOT)
    assert part.row_count == 2221
    assert set(part.panel.columns) == {
        "eth_open",
        "eth_high",
        "eth_low",
        "eth_close",
        "eth_volume",
        "btc_open",
        "btc_high",
        "btc_low",
        "btc_close",
        "btc_volume",
    }
    # Firewall: not one aligned row on/after the research cutoff / window end.
    assert bool((part.panel.index <= RESEARCH_CUTOFF_LAST_OPEN).all())
    assert bool((part.panel.index < WINDOW_END_EXCLUSIVE).all())
    assert part.last_open == RESEARCH_CUTOFF_LAST_OPEN
    # The candidate view exposes exactly the two joint close columns.
    cp = part.candidate_panel()
    assert list(cp.columns) == [jp.ETH_CLOSE, jp.BTC_CLOSE]
    assert len(cp) == 2221


def test_combined_fingerprint_binds_components() -> None:
    from eth_research.v2.strict import canonical_sha256

    part = jp.build_joint_partition(REPO_ROOT)
    expected = canonical_sha256(
        {
            "eth_dataset_fingerprint": part.eth_dataset_fingerprint,
            "btc_dataset_fingerprint": part.btc_dataset_fingerprint,
            "aligned_timestamp_fingerprint": part.aligned_timestamp_fingerprint,
            "eth_content_fingerprint": part.eth_content_fingerprint,
            "btc_content_fingerprint": part.btc_content_fingerprint,
        }
    )
    assert part.combined_partition_fingerprint == expected


def test_identity_records_both_instruments_and_policy() -> None:
    doc = json.loads((REPO_ROOT / jp.JOINT_PARTITION_IDENTITY_RELPATH).read_bytes())
    assert doc["instruments"] == ["BTC-USD", "ETH-USD"]
    assert doc["alignment_policy"] == "exact_shared_daily_opens"
    assert doc["base_currency"] == "USD"
    assert doc["no_row_at_or_after_cutoff"] is True
    assert doc["row_count"] == 2221


def test_builder_takes_no_caller_frame() -> None:
    # Substitution resistance by construction: the partition is derived ONLY from repo_root, so a
    # caller cannot inject a fabricated BTC/ETH frame, a forged quality report, or a copied
    # manifest — everything is re-derived from committed bytes (BTC drift detection is proven in
    # test_v2b_btc_dataset::test_verify_detects_raw_body_tamper).
    import inspect

    for fn in (jp.build_joint_partition, jp.build_partition_identity, jp.verify_joint_partition):
        params = list(inspect.signature(fn).parameters)
        assert params == ["repo_root"], (fn.__name__, params)


def test_verify_detects_a_forged_committed_identity(tmp_path: Path) -> None:
    # A forged committed identity that disagrees with the re-derived bytes fails verification.
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "research", root / "research")
    shutil.copytree(REPO_ROOT / "src", root / "src")
    for extra in ("pyproject.toml", "uv.lock"):
        shutil.copy2(REPO_ROOT / extra, root / extra)
    jp.verify_joint_partition(root)  # untouched copy verifies
    forged = json.loads((root / jp.JOINT_PARTITION_IDENTITY_RELPATH).read_bytes())
    forged["combined_partition_fingerprint"] = "0" * 64
    (root / jp.JOINT_PARTITION_IDENTITY_RELPATH).write_bytes(json.dumps(forged).encode())
    with pytest.raises(jp.JointPartitionError, match="does not reproduce"):
        jp.verify_joint_partition(root)
