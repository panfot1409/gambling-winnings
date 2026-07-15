"""Unit coverage for the M3D shared strict-validation surface."""

from __future__ import annotations

import json

import pytest

from eth_research.m3d import validation as v


def test_canonical_json_bytes_is_sorted_and_newline_terminated() -> None:
    out = v.canonical_json_bytes({"b": 1, "a": 2})
    assert out.endswith(b"\n")
    assert out.count(b"\n") >= 1
    # sorted keys: "a" precedes "b"
    assert out.index(b'"a"') < out.index(b'"b"')
    # reloads to the same object
    assert json.loads(out) == {"a": 2, "b": 1}


def test_canonical_json_bytes_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="not JSON compliant"):
        v.canonical_json_bytes({"x": float("nan")})
    with pytest.raises(ValueError, match="not JSON compliant"):
        v.canonical_json_bytes({"x": float("inf")})


def test_domain_sha256_separates_domains() -> None:
    payload = {"k": [1, 2, 3]}
    a = v.domain_sha256("alpha", payload)
    b = v.domain_sha256("beta", payload)
    assert a != b
    # deterministic
    assert a == v.domain_sha256("alpha", payload)
    assert len(a) == 64
    assert all(c in "0123456789abcdef" for c in a)


def test_domain_sha256_requires_domain() -> None:
    with pytest.raises(ValueError, match="domain must be a non-empty string"):
        v.domain_sha256("", {"k": 1})


def test_require_int_rejects_bool() -> None:
    assert v.require_int("n", 3) == 3
    with pytest.raises(ValueError, match="must be an integer"):
        v.require_int("n", True)
    with pytest.raises(ValueError, match="must be an integer"):
        v.require_int("n", 1.0)


def test_require_bool_rejects_int() -> None:
    assert v.require_bool("b", False) is False
    with pytest.raises(ValueError, match="must be a boolean"):
        v.require_bool("b", 0)
    with pytest.raises(ValueError, match="must be a boolean"):
        v.require_bool("b", 1)


def test_require_finite_float_rejects_bool_and_nonfinite() -> None:
    assert v.require_finite_float("x", 2) == 2.0
    assert v.require_finite_float("x", 2.5) == 2.5
    with pytest.raises(ValueError, match="must be a number"):
        v.require_finite_float("x", True)
    with pytest.raises(ValueError, match="must be finite"):
        v.require_finite_float("x", float("inf"))


def test_require_sha256_hex_format() -> None:
    good = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert v.require_sha256_hex("h", good) == good
    with pytest.raises(ValueError, match="64 lowercase hex"):
        v.require_sha256_hex("h", good.upper())  # uppercase rejected
    with pytest.raises(ValueError, match="64 lowercase hex"):
        v.require_sha256_hex("h", "sha256:" + good)  # prefix rejected
    with pytest.raises(ValueError, match="64 lowercase hex"):
        v.require_sha256_hex("h", good[:-1])  # wrong length


def test_require_exact_is_type_strict() -> None:
    assert v.require_exact("k", 5, 5) == 5
    with pytest.raises(ValueError, match="must be exactly"):
        v.require_exact("k", 5, "5")
    with pytest.raises(ValueError, match="must be exactly"):
        v.require_exact("k", True, 1)  # bool is not int here


def test_require_mapping_and_list_and_str() -> None:
    assert v.require_mapping("m", {"a": 1}) == {"a": 1}
    assert v.require_list("l", [1, 2]) == [1, 2]
    assert v.require_nonempty_str("s", "hi") == "hi"
    with pytest.raises(ValueError, match="must be a JSON object"):
        v.require_mapping("m", [1])
    with pytest.raises(ValueError, match="must be a JSON array"):
        v.require_list("l", {"a": 1})
    with pytest.raises(ValueError, match="must be a non-empty string"):
        v.require_nonempty_str("s", "")


def test_load_canonical_json_bytes_enforces_trailing_newline(tmp_path) -> None:
    good = tmp_path / "good.json"
    good.write_bytes(v.canonical_json_bytes({"a": 1}))
    raw, doc = v.load_canonical_json_bytes(good, "good")
    assert doc == {"a": 1}
    assert raw.endswith(b"\n")

    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{\n  "a": 1\n}')  # no trailing newline
    with pytest.raises(ValueError, match="must end with a trailing newline"):
        v.load_canonical_json_bytes(bad, "bad")


def test_require_string_sequence() -> None:
    assert v.require_string_sequence("s", ["a", "b"]) == ("a", "b")
    with pytest.raises(ValueError, match="must be a string"):
        v.require_string_sequence("s", ["a", 1])
