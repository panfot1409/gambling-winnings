"""The V2F-R containment gate must refuse, and refuse for the right reason.

A gate is only worth what its refusals are worth, so every case below drives the
real entry point against a real file and reads the refusal, rather than asserting
that some exception was raised.

The load-bearing case is ``test_a_deleted_record_still_refuses``. The intuitive
implementation — "no containment record, so nothing is contained" — makes
``rm governance/v2f/containment.json`` a complete bypass of the suspension. That
is the failure mode this file exists to pin down.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "tools/v2f_containment_gate.py"


def _load(name: str, path: Path) -> ModuleType:
    # tools/ is deliberately not a package (see tests/test_m3f_independence.py):
    # loading by file location keeps these scripts runnable with a bare
    # interpreter, which is what the workflow does before any environment sync.
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GATE_MODULE = _load("v2f_containment_gate", GATE)
RECORD_RELPATH: str = _GATE_MODULE.RECORD_RELPATH
ContainmentRefusal: type[Exception] = _GATE_MODULE.ContainmentRefusal
check = _GATE_MODULE.check

LIVE_RECORD = REPO_ROOT / RECORD_RELPATH


def _write(root: Path, payload: Any) -> Path:
    record = root / RECORD_RELPATH
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )
    return record


def _lifted() -> dict[str, Any]:
    return {
        "kind": "v2f_containment",
        "active": False,
        "lifted_by": "repository owner",
        "lifted_on": "2026-08-01",
    }


# --- the committed record --------------------------------------------------


def test_the_committed_record_is_active_and_refuses() -> None:
    """Containment is the current state of this repository, not a template."""
    assert LIVE_RECORD.is_file()
    payload = json.loads(LIVE_RECORD.read_text())
    assert payload["kind"] == "v2f_containment"
    assert payload["active"] is True
    assert payload["suspends_workflow_basename"] == "m3e-prospective-update.yml"

    with pytest.raises(ContainmentRefusal, match="SUSPENDED under V2F-R containment"):
        check(REPO_ROOT)


# --- refusals --------------------------------------------------------------


def test_a_deleted_record_still_refuses(tmp_path: Path) -> None:
    """Absence must not read as permission.

    If this ever passes, deleting one file resumes unattended market-data
    egress on a public repository.
    """
    with pytest.raises(ContainmentRefusal, match="Absence is refused, not permitted"):
        check(tmp_path)


def test_an_unattributed_lift_refuses(tmp_path: Path) -> None:
    _write(tmp_path, {"kind": "v2f_containment", "active": False})
    with pytest.raises(ContainmentRefusal, match="without lifted_by, lifted_on"):
        check(tmp_path)


def test_a_partially_attributed_lift_refuses(tmp_path: Path) -> None:
    _write(tmp_path, {"kind": "v2f_containment", "active": False, "lifted_by": "someone"})
    with pytest.raises(ContainmentRefusal, match="without lifted_on"):
        check(tmp_path)


def test_a_truthy_non_boolean_active_refuses(tmp_path: Path) -> None:
    """``active: "false"`` is a truthy string; typing it out avoids that trap."""
    _write(tmp_path, {"kind": "v2f_containment", "active": "false"})
    with pytest.raises(ContainmentRefusal, match="must be a JSON boolean, got str"):
        check(tmp_path)


def test_a_renamed_kind_refuses(tmp_path: Path) -> None:
    _write(tmp_path, {"kind": "something_else", "active": False, **_lifted()} | {"kind": "other"})
    with pytest.raises(ContainmentRefusal, match="not 'v2f_containment'"):
        check(tmp_path)


def test_malformed_json_refuses(tmp_path: Path) -> None:
    _write(tmp_path, "{not json")
    with pytest.raises(ContainmentRefusal, match="not valid JSON"):
        check(tmp_path)


def test_a_json_array_refuses(tmp_path: Path) -> None:
    _write(tmp_path, [{"kind": "v2f_containment", "active": False}])
    with pytest.raises(ContainmentRefusal, match="must be a JSON object"):
        check(tmp_path)


# --- the one way through ---------------------------------------------------


def test_an_attributed_lift_opens_the_gate(tmp_path: Path) -> None:
    """Proves the refusals above are about containment, not a gate stuck shut."""
    _write(tmp_path, _lifted())
    assert check(tmp_path) == "containment lifted by repository owner on 2026-08-01"


# --- the CLI the workflow actually invokes ---------------------------------


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_cli_exits_nonzero_against_the_live_repository() -> None:
    result = _run(REPO_ROOT)
    assert result.returncode == 1
    assert "REFUSED" in result.stderr


def test_the_cli_exits_zero_only_on_a_lawful_lift(tmp_path: Path) -> None:
    assert _run(tmp_path).returncode == 1  # absent
    _write(tmp_path, _lifted())
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "containment gate: open" in result.stdout
