"""V2C: the append-only OQ source-freeze supersession ledger (pre-registration correction).

Proves the committed supersession ledger records ``e4b3cc3`` as superseded while the OQ registry was
byte-empty, that a superseded freeze can never authorize registration or execution, and that every
tamper, deletion, duplicate, non-pristine, or path-substitution attempt is refused fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eth_research.v2c.oq.supersession import (
    EMPTY_SHA256,
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
    OQSupersessionError,
    append_supersession,
    assert_freeze_not_superseded,
    assert_freeze_superseded,
    build_supersession_record,
    read_supersession,
    record_supersession,
    superseded_commits,
    verify_supersession,
)

REPO = Path(__file__).resolve().parents[1]
_E4B3CC3 = "e4b3cc3d6ecfa0d58dd4c71c01f06b2e252ba6ee"
_UTC = "2026-07-21T09:54:52+00:00"
_SEALED = dict.fromkeys(SEALED_LEDGER_RELPATHS, EMPTY_SHA256)


def _append(path: Path, **over: object) -> object:
    kw: dict[str, object] = {
        "supersession_id": "oq_source_freeze_supersession_001",
        "superseded_commit": _E4B3CC3,
        "superseded_freeze_relpath": "governance/v2c/oq_source_freeze.json",
        "superseded_freeze_artifact_sha256": "a" * 64,
        "registry_relpath": "governance/v2c/oq_registry.jsonl",
        "registry_byte_count": 0,
        "registry_sha256": EMPTY_SHA256,
        "registry_event_count": 0,
        "sealed_ledger_sha256": dict(_SEALED),
        "generated_utc": _UTC,
        "package_version": "2.0.0.dev2",
    }
    kw.update(over)
    return append_supersession(path, **kw)  # type: ignore[arg-type]


def _build(**over: object) -> object:
    kw: dict[str, object] = {
        "supersession_id": "oq_source_freeze_supersession_001",
        "superseded_commit": _E4B3CC3,
        "superseded_freeze_relpath": "governance/v2c/oq_source_freeze.json",
        "superseded_freeze_artifact_sha256": "a" * 64,
        "registry_relpath": "governance/v2c/oq_registry.jsonl",
        "registry_byte_count": 0,
        "registry_sha256": EMPTY_SHA256,
        "registry_event_count": 0,
        "sealed_ledger_sha256": dict(_SEALED),
        "generated_utc": _UTC,
        "package_version": "2.0.0.dev2",
        "prev_hash": "0" * 64,
    }
    kw.update(over)
    return build_supersession_record(**kw)  # type: ignore[arg-type]


def _fake_pristine_repo(root: Path) -> None:
    (root / "governance/v2c").mkdir(parents=True, exist_ok=True)
    (root / "governance/v2c/oq_registry.jsonl").write_bytes(b"")
    (root / "governance/v2c/oq_source_freeze.json").write_bytes(b'{"freeze":1}\n')
    for rel in SEALED_LEDGER_RELPATHS:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def _tamper(path: Path, **changes: object) -> None:
    line = json.loads(path.read_bytes())
    line.update(changes)
    path.write_bytes((json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n").encode())


# --------------------------------------------------------------------------- #
# The committed ledger                                                        #
# --------------------------------------------------------------------------- #
def test_committed_ledger_is_clean_and_records_e4b3cc3() -> None:
    p = REPO / OQ_SUPERSESSION_PATH
    assert verify_supersession(p) == []
    assert _E4B3CC3 in superseded_commits(p)
    assert_freeze_superseded(p, _E4B3CC3)  # present on record


def test_committed_ledger_leaves_the_registry_pristine() -> None:
    assert (REPO / "governance/v2c/oq_registry.jsonl").stat().st_size == 0


# --------------------------------------------------------------------------- #
# A superseded freeze cannot authorize registration or execution              #
# --------------------------------------------------------------------------- #
def test_superseded_freeze_cannot_authorize_registration(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    with pytest.raises(OQSupersessionError, match="superseded"):
        assert_freeze_not_superseded(led, _E4B3CC3)


def test_superseded_freeze_cannot_authorize_execution(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    assert_freeze_not_superseded(led, "b" * 40)  # a different (replacement) freeze is allowed
    with pytest.raises(OQSupersessionError):
        assert_freeze_not_superseded(led, _E4B3CC3)  # the superseded one is refused


# --------------------------------------------------------------------------- #
# Tamper / deletion / status detection                                        #
# --------------------------------------------------------------------------- #
def test_replacement_status_active_is_refused() -> None:
    with pytest.raises(ValueError, match="replacement_freeze_status"):
        _build(replacement_freeze_status="active", replacement_freeze_commit=None)


def test_deleting_the_record_is_detected(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    assert_freeze_superseded(led, _E4B3CC3)
    led.unlink()
    with pytest.raises(OQSupersessionError, match="not recorded as superseded"):
        assert_freeze_superseded(led, _E4B3CC3)


def test_changing_the_reason_is_detected(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    _tamper(led, reason="a different reason")
    with pytest.raises(OQSupersessionError):
        read_supersession(led)


def test_tampered_started_flag_is_refused(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    _tamper(led, no_qualification_started=False)
    with pytest.raises(OQSupersessionError):
        read_supersession(led)


def test_bool_as_count_is_refused(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    _tamper(led, registry_byte_count=True)
    with pytest.raises(ValueError, match="bool is rejected"):
        read_supersession(led)


# --------------------------------------------------------------------------- #
# Pristine-state preconditions                                                #
# --------------------------------------------------------------------------- #
def test_nonempty_registry_at_supersession_refused() -> None:
    with pytest.raises(OQSupersessionError, match="byte-empty"):
        _build(registry_byte_count=5)


def test_started_qualification_at_supersession_refused() -> None:
    with pytest.raises(OQSupersessionError, match=r"byte-empty|unconsumed"):
        _build(registry_event_count=1)


def test_non_git_sha_commit_is_refused() -> None:
    with pytest.raises(OQSupersessionError, match="git commit sha"):
        _build(superseded_commit="not-a-sha")


# --------------------------------------------------------------------------- #
# Path / chain / lifecycle attacks                                            #
# --------------------------------------------------------------------------- #
def test_symlinked_ledger_is_refused(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    link = tmp_path / "link.jsonl"
    link.symlink_to(led)
    with pytest.raises(OQSupersessionError, match="symlink"):
        read_supersession(link)


def test_duplicate_supersession_ids_are_refused(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led)
    with pytest.raises(OQSupersessionError, match=r"duplicate id|superseded twice"):
        _append(led, superseded_commit="f" * 40)  # same id, different commit


def test_binding_an_already_superseded_replacement_is_refused(tmp_path: Path) -> None:
    led = tmp_path / "s.jsonl"
    _append(led, supersession_id="oq_source_freeze_supersession_001", superseded_commit="a" * 40)
    with pytest.raises(OQSupersessionError, match="itself superseded"):
        _append(
            led,
            supersession_id="oq_source_freeze_supersession_002",
            superseded_commit="b" * 40,
            replacement_freeze_status="bound",
            replacement_freeze_commit="a" * 40,  # already superseded above
        )


# --------------------------------------------------------------------------- #
# The live-state-bound recorder                                               #
# --------------------------------------------------------------------------- #
def test_record_supersession_binds_live_pristine_state(tmp_path: Path) -> None:
    _fake_pristine_repo(tmp_path)
    rec = record_supersession(
        tmp_path,
        supersession_id="oq_source_freeze_supersession_001",
        superseded_commit=_E4B3CC3,
        superseded_freeze_relpath="governance/v2c/oq_source_freeze.json",
        generated_utc=_UTC,
        package_version="2.0.0.dev2",
    )
    assert rec.registry_sha256 == EMPTY_SHA256
    assert rec.registry_byte_count == 0
    expect = hashlib.sha256(
        (tmp_path / "governance/v2c/oq_source_freeze.json").read_bytes()
    ).hexdigest()
    assert rec.superseded_freeze_artifact_sha256 == expect
    assert verify_supersession(tmp_path / OQ_SUPERSESSION_PATH) == []


def test_record_supersession_refused_when_registry_nonempty(tmp_path: Path) -> None:
    _fake_pristine_repo(tmp_path)
    (tmp_path / "governance/v2c/oq_registry.jsonl").write_bytes(b'{"seq":0}\n')
    with pytest.raises(OQSupersessionError, match="not byte-empty"):
        record_supersession(
            tmp_path,
            supersession_id="oq_source_freeze_supersession_002",
            superseded_commit="a" * 40,
            superseded_freeze_relpath="governance/v2c/oq_source_freeze.json",
            generated_utc=_UTC,
            package_version="2.0.0.dev2",
        )


def test_record_supersession_refused_when_sealed_ledger_nonempty(tmp_path: Path) -> None:
    _fake_pristine_repo(tmp_path)
    (tmp_path / SEALED_LEDGER_RELPATHS[0]).write_bytes(b"contaminated\n")
    with pytest.raises(OQSupersessionError, match="not byte-empty"):
        record_supersession(
            tmp_path,
            supersession_id="oq_source_freeze_supersession_003",
            superseded_commit="a" * 40,
            superseded_freeze_relpath="governance/v2c/oq_source_freeze.json",
            generated_utc=_UTC,
            package_version="2.0.0.dev2",
        )
