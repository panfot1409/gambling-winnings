"""V2C section 35 (OQ-E): the operational-qualification source freeze.

Proves the committed ``governance/v2c/oq_source_freeze.json`` is a pure, reproducible hash of the
qualification-defining source, that the aggregate digest binds every frozen path, and that any drift
(a changed source byte, a symlink, a missing file) is refused fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research.v2.strict import canonical_sha256
from eth_research.v2c.oq.freeze import (
    OQ_SOURCE_FREEZE_RELPATH,
    OQSourceFreezeError,
    build_oq_source_freeze,
    oq_source_freeze_digest,
    render_oq_source_freeze_bytes,
    verify_oq_source_freeze,
    write_oq_source_freeze,
)

REPO = Path(__file__).resolve().parents[1]

# The frozen relpaths, read from the module's own committed set via a build against the real repo.
_FROZEN = build_oq_source_freeze(REPO)
_ALL_RELPATHS = tuple(_FROZEN["frozen_source_sha256"]) + tuple(_FROZEN["frozen_artifact_sha256"])


def _make_fake_repo(root: Path) -> None:
    """Materialize every frozen relpath as a tiny distinct stub file under ``root``."""
    for rel in _ALL_RELPATHS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"stub for {rel}\n", encoding="utf-8")


def test_committed_freeze_reproduces_from_live_source() -> None:
    verify_oq_source_freeze(REPO)  # must not raise
    committed = (REPO / OQ_SOURCE_FREEZE_RELPATH).read_bytes()
    assert committed == render_oq_source_freeze_bytes(build_oq_source_freeze(REPO))


def test_build_is_deterministic() -> None:
    assert build_oq_source_freeze(REPO) == build_oq_source_freeze(REPO)


def test_digest_binds_every_frozen_path() -> None:
    freeze = build_oq_source_freeze(REPO)
    merged = {**freeze["frozen_source_sha256"], **freeze["frozen_artifact_sha256"]}
    assert freeze["source_freeze_digest"] == canonical_sha256(merged)
    # Flipping any single hash changes the aggregate digest.
    victim = next(iter(merged))
    mutated = {**merged, victim: "0" * 64}
    assert canonical_sha256(mutated) != freeze["source_freeze_digest"]


def test_freeze_covers_the_qualification_defining_source() -> None:
    source = build_oq_source_freeze(REPO)["frozen_source_sha256"]
    for expected in (
        "src/eth_research/v2c/firewall.py",
        "src/eth_research/v2c/oq/events.py",
        "src/eth_research/v2c/oq/slo.py",
        "src/eth_research/v2c/oq/registry.py",
        "src/eth_research/v2c/buyer/boundary.py",
        "src/eth_research/v2c/readiness.py",
    ):
        assert expected in source, expected


def test_verify_detects_source_drift(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    verify_oq_source_freeze(tmp_path)  # clean
    # Change one frozen source byte: the committed manifest no longer reproduces.
    victim = tmp_path / "src/eth_research/v2c/firewall.py"
    victim.write_text(victim.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    with pytest.raises(OQSourceFreezeError, match=r"did not reproduce|changed after"):
        verify_oq_source_freeze(tmp_path)


def test_missing_frozen_file_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    (tmp_path / "src/eth_research/v2c/firewall.py").unlink()
    with pytest.raises(OQSourceFreezeError, match="missing"):
        build_oq_source_freeze(tmp_path)


def test_symlinked_frozen_file_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    victim = tmp_path / "src/eth_research/v2c/readiness.py"
    victim.unlink()
    victim.symlink_to(tmp_path / "src/eth_research/v2c/firewall.py")
    with pytest.raises(OQSourceFreezeError, match="symlink"):
        build_oq_source_freeze(tmp_path)


def test_digest_helper_matches_build() -> None:
    assert oq_source_freeze_digest(REPO) == build_oq_source_freeze(REPO)["source_freeze_digest"]
