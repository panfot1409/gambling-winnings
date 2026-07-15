"""Transactional publication tests (M3D section 17).

Prove the all-or-nothing publisher: a healthy batch writes every artifact and a
failure at any position rolls the whole batch back, leaving fresh files removed
and overwritten files restored to their exact previous bytes, with no partial
bundle or dangling completeness marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research._atomic import write_atomic as _real_write_atomic
from eth_research.m3d import publication
from eth_research.m3d.publication import (
    ProspectivePublicationError,
    build_publication_manifest_bytes,
    publish_bundle,
)
from eth_research.m3d.validation import sha256_bytes

_A = ("research/m3d/a.json", b'{"k": 1}\n')
_B = ("research/m3d/b.jsonl", b'{"n": 2}\n')


def _prepare(root: Path, blobs: tuple[tuple[str, bytes], ...]) -> None:
    for rel, _ in blobs:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)


def test_publish_bundle_writes_all_and_returns_digests(tmp_path: Path) -> None:
    _prepare(tmp_path, (_A, _B))
    digests = publish_bundle(tmp_path, [_A, _B])
    assert (tmp_path / _A[0]).read_bytes() == _A[1]
    assert (tmp_path / _B[0]).read_bytes() == _B[1]
    assert dict(digests) == {_A[0]: sha256_bytes(_A[1]), _B[0]: sha256_bytes(_B[1])}


def test_publish_bundle_rejects_duplicate_relpaths(tmp_path: Path) -> None:
    _prepare(tmp_path, (_A,))
    with pytest.raises(ProspectivePublicationError, match="duplicate relpath"):
        publish_bundle(tmp_path, [_A, _A])


def test_rollback_is_clean_on_a_fresh_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare(tmp_path, (_A, _B))
    real = _real_write_atomic
    armed = {"on": True}

    def flaky(path: Path, data: bytes) -> None:
        if armed["on"] and path.name == "b.jsonl":
            armed["on"] = False
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(publication, "write_atomic", flaky)
    with pytest.raises(ProspectivePublicationError, match="rolled back"):
        publish_bundle(tmp_path, [_A, _B])
    # Fresh state: neither newly created file survives.
    assert not (tmp_path / _A[0]).exists()
    assert not (tmp_path / _B[0]).exists()


def test_rollback_restores_prior_bytes_on_an_overwrite_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare(tmp_path, (_A, _B))
    (tmp_path / _A[0]).write_bytes(b'{"old": "a"}\n')
    (tmp_path / _B[0]).write_bytes(b'{"old": "b"}\n')
    real = _real_write_atomic
    armed = {"on": True}

    def flaky(path: Path, data: bytes) -> None:
        if armed["on"] and path.name == "b.jsonl":
            armed["on"] = False
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(publication, "write_atomic", flaky)
    with pytest.raises(ProspectivePublicationError):
        publish_bundle(tmp_path, [_A, _B])
    # Overwrite state: the first file is restored to its exact previous bytes.
    assert (tmp_path / _A[0]).read_bytes() == b'{"old": "a"}\n'
    assert (tmp_path / _B[0]).read_bytes() == b'{"old": "b"}\n'


def test_rollback_on_corrupt_readback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare(tmp_path, (_A, _B))
    real = _real_write_atomic

    def corrupt(path: Path, data: bytes) -> None:
        real(path, data + (b"X" if path.name == "b.jsonl" else b""))

    monkeypatch.setattr(publication, "write_atomic", corrupt)
    with pytest.raises(ProspectivePublicationError, match="readback mismatch"):
        publish_bundle(tmp_path, [_A, _B])
    assert not (tmp_path / _A[0]).exists()
    assert not (tmp_path / _B[0]).exists()


def test_publication_manifest_is_a_pure_function_of_the_batch() -> None:
    a = build_publication_manifest_bytes([_A, _B])
    b = build_publication_manifest_bytes([_B, _A])  # order-independent (sorted)
    assert a == b
    assert sha256_bytes(_A[1]).encode() in a  # binds each artifact hash
