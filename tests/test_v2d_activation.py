"""V2D activation-anchor + runtime-gate tests.

The committed ``governance/v2d/prospective_activation.json`` must round-trip
byte-for-byte from the pure-constant builder and pass the full fail-closed gate on
the real tree; every tamper, omission, weakening, or integrity failure on a
disposable copy must refuse activation with :class:`V2DActivationError`. No test
mutates the real repository.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from eth_research.m3e.accepted_base import AcceptedProspectiveBase
from eth_research.v2d.activation import (
    ANCHOR_RELPATH,
    AUTHORIZED_REPOSITORY,
    AUTHORIZED_WORKFLOW_BASENAME,
    GENESIS_CONTENT_FINGERPRINT,
    V2DActivationError,
    build_activation_anchor_document,
    load_activation_anchor,
    render_anchor_bytes,
    verify_activation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The minimal committed file set the full gate transitively verifies. The disposable
# fixture copies exactly this, so tamper tests never touch the real tree.
_TREE_COPY: tuple[str, ...] = (
    "research/m3d",
    "research/m3c/candidate_decision.json",
    "research/m2b/dataset_lock.json",
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3e/accepted_base.json",
    ANCHOR_RELPATH,
    f".github/workflows/{AUTHORIZED_WORKFLOW_BASENAME}",
)


def _gate(root: Path) -> tuple[dict[str, object], AcceptedProspectiveBase]:
    return verify_activation(
        root,
        workflow_basename=AUTHORIZED_WORKFLOW_BASENAME,
        repository=AUTHORIZED_REPOSITORY,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in _TREE_COPY:
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return tmp_path


# --------------------------------------------------------------------------------------------------
# Round-trip + real-tree acceptance
# --------------------------------------------------------------------------------------------------


def test_committed_anchor_is_byte_identical_to_the_constant_rebuild() -> None:
    assert (REPO_ROOT / ANCHOR_RELPATH).read_bytes() == render_anchor_bytes()


def test_full_gate_passes_on_the_real_tree() -> None:
    anchor, base = _gate(REPO_ROOT)
    assert anchor["kind"] == "v2d_prospective_activation"
    assert base.row_count >= 3
    assert base.document["evaluation_authorized"] is False


def test_anchor_records_the_authorization_exclusions() -> None:
    doc = build_activation_anchor_document()
    exclusions = doc["authorization_exclusions"]
    assert isinstance(exclusions, list)
    assert len(exclusions) == 12
    assert "public publication" in exclusions
    assert "order routing" in exclusions
    assert doc["cohort_identity"]["genesis_content_fingerprint"] == GENESIS_CONTENT_FINGERPRINT


def test_gate_passes_on_a_faithful_disposable_copy(tree: Path) -> None:
    _anchor, base = _gate(tree)
    assert base.row_count == 3


# --------------------------------------------------------------------------------------------------
# Fail-closed matrix (disposable copies only)
# --------------------------------------------------------------------------------------------------


def test_missing_anchor_refuses(tree: Path) -> None:
    (tree / ANCHOR_RELPATH).unlink()
    with pytest.raises(V2DActivationError, match="NOT ACTIVATED"):
        _gate(tree)


def test_tampered_anchor_bytes_refuse(tree: Path) -> None:
    path = tree / ANCHOR_RELPATH
    path.write_bytes(path.read_bytes().replace(b"2026-07-23", b"2026-07-24"))
    with pytest.raises(V2DActivationError):
        load_activation_anchor(tree)


def test_weakened_standing_requirement_refuses(tree: Path) -> None:
    path = tree / ANCHOR_RELPATH
    tampered = path.read_bytes().replace(
        b'"evaluation_authorized_must_remain_false": true',
        b'"evaluation_authorized_must_remain_false": false',
    )
    assert tampered != path.read_bytes()
    path.write_bytes(tampered)
    with pytest.raises(V2DActivationError):
        _gate(tree)


def test_wrong_workflow_basename_refuses(tree: Path) -> None:
    with pytest.raises(V2DActivationError, match="not the running workflow"):
        verify_activation(
            tree, workflow_basename="m3e-replay.yml", repository=AUTHORIZED_REPOSITORY
        )


def test_wrong_repository_refuses(tree: Path) -> None:
    with pytest.raises(V2DActivationError, match="repository"):
        verify_activation(
            tree,
            workflow_basename=AUTHORIZED_WORKFLOW_BASENAME,
            repository="someone-else/fork",
        )


def test_missing_workflow_file_refuses(tree: Path) -> None:
    (tree / ".github/workflows" / AUTHORIZED_WORKFLOW_BASENAME).unlink()
    with pytest.raises(V2DActivationError, match="workflow file missing"):
        _gate(tree)


def test_nonempty_sealed_prospective_ledger_refuses(tree: Path) -> None:
    (tree / "research/m3d/prospective_evaluations.jsonl").write_bytes(b'{"leak":1}\n')
    with pytest.raises(V2DActivationError):
        _gate(tree)


def test_tampered_accepted_evidence_refuses(tree: Path) -> None:
    # A single flipped byte anywhere in the committed cohort evidence must refuse.
    #
    # The mutation is derived from the file rather than hard-coded. It used to
    # search for `"row_count": 3`; once the accepted cohort grew past 3 that
    # string was absent, the replace became a no-op, and the test asserted a
    # refusal for a tree nobody had tampered with. Confirming the mutation
    # changed bytes is what makes the assertion below mean anything.
    manifest = tree / "research/m3d/prospective_manifest.json"
    before = manifest.read_bytes()
    match = re.search(rb'"row_count": (\d+)', before)
    assert match is not None, "no row_count to tamper with"
    after = before.replace(match.group(0), b'"row_count": %d' % (int(match.group(1)) + 1), 1)
    assert after != before, "mutation did not change any bytes"
    manifest.write_bytes(after)
    with pytest.raises(V2DActivationError, match="accepted base failed verification"):
        _gate(tree)


def test_tampered_segment_chain_refuses(tree: Path) -> None:
    segments = tree / "research/m3d/prospective_segments.jsonl"
    segments.write_bytes(segments.read_bytes() + b"\n")
    with pytest.raises(V2DActivationError):
        _gate(tree)


def test_cli_verify_refuses_without_anchor(tmp_path: Path) -> None:
    from eth_research.v2d.__main__ import main

    code = main(
        [
            "verify",
            "--repo-root",
            str(tmp_path),
            "--workflow-basename",
            AUTHORIZED_WORKFLOW_BASENAME,
            "--repository",
            AUTHORIZED_REPOSITORY,
        ]
    )
    assert code == 1


def test_cli_verify_passes_on_real_tree(capsys: pytest.CaptureFixture[str]) -> None:
    from eth_research.v2d.__main__ import main

    code = main(
        [
            "verify",
            "--repo-root",
            str(REPO_ROOT),
            "--workflow-basename",
            AUTHORIZED_WORKFLOW_BASENAME,
            "--repository",
            AUTHORIZED_REPOSITORY,
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "V2D ACTIVATION GATE PASSED" in out
    assert "evaluation_authorized: False" in out
