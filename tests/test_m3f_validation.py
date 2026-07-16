"""Strict parsing, safe-path, and canonical-bytes invariants for M3F (commit 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    normalize_relpath,
    require_bool,
    require_int,
    require_sha256_hex,
    safe_repo_path,
    strict_jsonl_records,
)


def _canon(payload: object) -> bytes:
    return canonical_json_bytes(payload)


def test_load_canonical_json_roundtrips_canonical_bytes() -> None:
    payload = {"b": 2, "a": [1, 2, 3]}
    assert load_canonical_json(_canon(payload), "x") == payload


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1}',  # no trailing newline
        b'{"a": 1, "a": 2}\n',  # duplicate key
        b'{"a": NaN}\n',  # non-finite
        b'{"a": Infinity}\n',  # non-finite
        b'{"a": 1}\n{"b": 2}\n',  # trailing data
        b"\xff\xfe\n",  # non-utf8
        b'{"a": 1e400}\n',  # exponent overflow
    ],
)
def test_load_canonical_json_rejects_malformed(raw: bytes) -> None:
    with pytest.raises(M3FValidationError):
        load_canonical_json(raw, "x")


def test_load_canonical_json_rejects_oversize() -> None:
    with pytest.raises(M3FValidationError, match="ceiling"):
        load_canonical_json(b"[" + b"0," * 5_000_000 + b"0]\n", "big")


def test_strict_jsonl_rejects_empty_line_and_missing_newline() -> None:
    assert strict_jsonl_records(b'{"a": 1}\n{"b": 2}\n', "j") == [{"a": 1}, {"b": 2}]
    with pytest.raises(M3FValidationError):
        strict_jsonl_records(b'{"a": 1}', "j")  # no trailing newline
    with pytest.raises(M3FValidationError):
        strict_jsonl_records(b'{"a": 1}\n\n{"b": 2}\n', "j")  # empty line


@pytest.mark.parametrize(
    "bad",
    [
        "/abs/path",
        "../escape",
        "a/../b",
        "a//b",
        "a/./b",
        "back\\slash",
        "trailing/",
        "nul\x00path",
        "",
    ],
)
def test_normalize_relpath_rejects_unsafe(bad: str) -> None:
    with pytest.raises(M3FValidationError):
        normalize_relpath(bad, "p")


def test_normalize_relpath_accepts_clean() -> None:
    assert normalize_relpath("research/m3f/freeze_catalog.json", "p") == (
        "research/m3f/freeze_catalog.json"
    )


def test_safe_repo_path_blocks_escape_and_symlink(tmp_path: Path) -> None:
    (tmp_path / "research").mkdir()
    (tmp_path / "research/ok.json").write_text("{}")
    assert safe_repo_path(tmp_path, "research/ok.json", "p").name == "ok.json"
    # symlink component is refused
    (tmp_path / "link").symlink_to(tmp_path / "research")
    with pytest.raises(M3FValidationError, match="symlink"):
        safe_repo_path(tmp_path, "link/ok.json", "p")


def test_require_bool_int_reject_cross_type() -> None:
    assert require_bool(True, "b") is True
    assert require_int(5, "i") == 5
    with pytest.raises(M3FValidationError):
        require_int(True, "i")  # bool is not int here
    with pytest.raises(M3FValidationError):
        require_bool(1, "b")  # int is not bool
    with pytest.raises(M3FValidationError):
        require_int("5", "i")  # numeric string not coerced


def test_require_sha256_hex() -> None:
    assert require_sha256_hex("a" * 64, "h") == "a" * 64
    for bad in ["A" * 64, "a" * 63, "g" * 64, 123]:
        with pytest.raises(M3FValidationError):
            require_sha256_hex(bad, "h")


def test_normalize_relpath_rejects_non_nfc_unicode_alias() -> None:
    # "cafe" + COMBINING ACUTE ACCENT (U+0301) is a decomposed (non-NFC) alias of
    # the precomposed "caf\u00e9"; a catalog must not accept both as distinct paths.
    decomposed = "cafe\u0301/x.json"
    with pytest.raises(M3FValidationError, match="non-NFC"):
        normalize_relpath(decomposed, "p")
