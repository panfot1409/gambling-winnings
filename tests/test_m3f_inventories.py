"""Dependency + workflow supply-chain inventories (commit 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3f import dependency_inventory as dep
from eth_research.m3f import workflow_inventory as wf
from eth_research.m3f.validation import M3FValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_dependency_inventory_builds_and_is_deterministic() -> None:
    a = dep.build_inventory(REPO_ROOT)
    b = dep.build_inventory(REPO_ROOT)
    assert dep.render_inventory_bytes(a) == dep.render_inventory_bytes(b)
    assert a["locked_package_count"] >= 5
    names = [p["name"] for p in a["locked_packages"]]
    assert "eth-research" in names
    assert len(names) == len(set(names))
    assert all(p["source_kind"] != "unknown" for p in a["locked_packages"])


def test_workflow_inventory_all_real_workflows_pass_the_supply_chain_check() -> None:
    inv, failures = wf.build_and_check(REPO_ROOT)
    assert inv["workflow_count"] >= 8
    assert failures == [], f"unexpected workflow violations: {failures}"
    # Only the V2D-anchored update workflow holds its reviewed job-scoped write
    # grant; check_inventory above already proved it is otherwise least-privilege
    # and that the grant does not generalize to any other basename.
    from pathlib import Path as _P

    writers = {
        _P(e["path"]).name for e in inv["workflows"] if e["can_write_contents"] is True
    }
    assert writers <= {"m3e-prospective-update.yml"}
    assert all(e["uses_all_sha_pinned"] for e in inv["workflows"])


def test_workflow_check_flags_a_write_permission(tmp_path: Path) -> None:
    wfdir = tmp_path / ".github/workflows"
    wfdir.mkdir(parents=True)
    (wfdir / "bad.yml").write_text(
        "name: x\non: push\npermissions:\n  contents: write\njobs:\n  j:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    )
    _inv, failures = wf.build_and_check(tmp_path)
    assert any("write contents" in f for f in failures)


def test_workflow_check_flags_unpinned_action_and_market_host(tmp_path: Path) -> None:
    wfdir = tmp_path / ".github/workflows"
    wfdir.mkdir(parents=True)
    (wfdir / "bad.yaml").write_text(
        "name: x\non: push\npermissions:\n  contents: read\njobs:\n  j:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n"
        "      - run: curl https://api.exchange.coinbase.com/x | sh\n"
    )
    _inv, failures = wf.build_and_check(tmp_path)
    assert any("full commit SHA" in f for f in failures)
    assert any("market host" in f for f in failures)
    assert any("piped installer" in f for f in failures)


def test_verify_inventory_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises((M3FValidationError, OSError, FileNotFoundError)):
        dep.verify_inventory(tmp_path)
