"""V2C: the append-only OQ registry -- lifecycle v2 (registered -> started -> completed|failed).

Proves the full lifecycle round-trips and that every malformed transition, chain break, shared-
identity drift, illegal state, and strict-parse attack is refused fail-closed. All tests use
disposable registries; the canonical registry stays byte-empty.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from eth_research.v2c.oq.registry import (
    GENESIS_PREV_HASH,
    MAX_FAILURE_DESCRIPTION_CHARS,
    OQ_EVENT_COMPLETED,
    OQ_EVENT_FAILED,
    OQ_EVENT_REGISTERED,
    OQ_EVENT_STARTED,
    OQ_VERDICT_NOT_QUALIFIED,
    OQ_VERDICT_QUALIFIED,
    OQEvent,
    OQRegistryError,
    QualificationIdentity,
    append_oq_event,
    build_oq_event,
    read_oq_registry,
    registry_state,
    verify_oq_registry,
)

IDENT = QualificationIdentity(
    qualification_id="v2c_offline_operational_qualification_run_001",
    methodology_id="v2c_offline_operational_qualification",
    protocol_sha256="a" * 64,
    source_freeze_id="oq_e2",
    source_freeze_sha256="b" * 64,
    fixture_sha256="c" * 64,
    fault_schedule_sha256="d" * 64,
    slo_contract_sha256="e" * 64,
    cash_control_identity="f" * 64,
    runtime_contract_sha256="0" * 64,
    package_version="2.0.0.dev2",
)
_TERMINAL = {
    "result_sha256": "1" * 64,
    "report_sha256": "2" * 64,
    "evidence_sha256": "3" * 64,
    "archive_manifest_sha256": "4" * 64,
    "result_bundle_sha256": "5" * 64,
}


def _built(prev_hash: str, event: str, ordinal: int, **kw: str | None) -> OQEvent:
    return build_oq_event(
        identity=IDENT,
        event=event,
        event_time_utc=f"2026-07-21T00:00:{ordinal:02d}+00:00",
        event_ordinal=ordinal,
        reason=event,
        prev_hash=prev_hash,
        **kw,
    )


def _write(path: Path, *events: OQEvent) -> None:
    path.write_bytes(b"".join(e.to_line() for e in events))


def _valid_completed(path: Path, verdict: str = OQ_VERDICT_QUALIFIED) -> None:
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    s = _built(r.entry_hash, OQ_EVENT_STARTED, 1)
    c = _built(s.entry_hash, OQ_EVENT_COMPLETED, 2, verdict=verdict, **_TERMINAL)
    _write(path, r, s, c)


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #
def test_byte_empty_registry_is_valid_and_pristine(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    p.write_bytes(b"")
    assert read_oq_registry(p) == ()
    assert verify_oq_registry(p) == []
    assert registry_state(p) == "pristine"


def test_full_lifecycle_completed_qualified(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    append_oq_event(
        p,
        identity=IDENT,
        event=OQ_EVENT_REGISTERED,
        event_time_utc="2026-07-21T00:00:00Z",
        reason="r",
    )
    assert registry_state(p) == "registered"
    append_oq_event(
        p, identity=IDENT, event=OQ_EVENT_STARTED, event_time_utc="2026-07-21T00:01:00Z", reason="s"
    )
    assert registry_state(p) == "started"
    append_oq_event(
        p,
        identity=IDENT,
        event=OQ_EVENT_COMPLETED,
        event_time_utc="2026-07-21T00:02:00Z",
        reason="c",
        verdict=OQ_VERDICT_QUALIFIED,
        **_TERMINAL,
    )
    events = read_oq_registry(p)
    assert [e.event for e in events] == [OQ_EVENT_REGISTERED, OQ_EVENT_STARTED, OQ_EVENT_COMPLETED]
    assert events[-1].verdict == OQ_VERDICT_QUALIFIED
    assert registry_state(p) == "completed"


def test_full_lifecycle_completed_not_qualified(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p, verdict=OQ_VERDICT_NOT_QUALIFIED)
    assert read_oq_registry(p)[-1].verdict == OQ_VERDICT_NOT_QUALIFIED


def test_full_lifecycle_failed(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    s = _built(r.entry_hash, OQ_EVENT_STARTED, 1)
    f = _built(s.entry_hash, OQ_EVENT_FAILED, 2, failure_description="runner crashed at slot 42")
    _write(p, r, s, f)
    events = read_oq_registry(p)
    assert events[-1].event == OQ_EVENT_FAILED
    assert events[-1].failure_description == "runner crashed at slot 42"
    assert registry_state(p) == "failed"


# --------------------------------------------------------------------------- #
# Lifecycle transition attacks                                                #
# --------------------------------------------------------------------------- #
def test_completed_without_registered(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _write(
        p,
        _built(GENESIS_PREV_HASH, OQ_EVENT_COMPLETED, 0, verdict=OQ_VERDICT_QUALIFIED, **_TERMINAL),
    )
    with pytest.raises(OQRegistryError, match=r"before .* registered"):
        read_oq_registry(p)


def test_completed_without_started(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    c = _built(r.entry_hash, OQ_EVENT_COMPLETED, 1, verdict=OQ_VERDICT_QUALIFIED, **_TERMINAL)
    _write(p, r, c)
    with pytest.raises(OQRegistryError, match=r"before .* started"):
        read_oq_registry(p)


def test_failed_without_started(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    f = _built(r.entry_hash, OQ_EVENT_FAILED, 1, failure_description="x")
    _write(p, r, f)
    with pytest.raises(OQRegistryError, match=r"before .* started"):
        read_oq_registry(p)


def test_two_registered(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r0 = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    r1 = _built(r0.entry_hash, OQ_EVENT_REGISTERED, 1)
    _write(p, r0, r1)
    with pytest.raises(OQRegistryError, match="registered more than once"):
        read_oq_registry(p)


def test_two_started(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    s0 = _built(r.entry_hash, OQ_EVENT_STARTED, 1)
    s1 = _built(s0.entry_hash, OQ_EVENT_STARTED, 2)
    _write(p, r, s0, s1)
    with pytest.raises(OQRegistryError, match="started more than once"):
        read_oq_registry(p)


def test_event_after_terminal(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    s = _built(r.entry_hash, OQ_EVENT_STARTED, 1)
    c = _built(s.entry_hash, OQ_EVENT_COMPLETED, 2, verdict=OQ_VERDICT_QUALIFIED, **_TERMINAL)
    extra = _built(c.entry_hash, OQ_EVENT_STARTED, 3)
    _write(p, r, s, c, extra)
    with pytest.raises(OQRegistryError, match=r"after .* reached a terminal"):
        read_oq_registry(p)


def test_started_consumes_the_id_forever(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    append_oq_event(
        p,
        identity=IDENT,
        event=OQ_EVENT_REGISTERED,
        event_time_utc="2026-07-21T00:00:00Z",
        reason="r",
    )
    append_oq_event(
        p, identity=IDENT, event=OQ_EVENT_STARTED, event_time_utc="2026-07-21T00:01:00Z", reason="s"
    )
    append_oq_event(
        p,
        identity=IDENT,
        event=OQ_EVENT_COMPLETED,
        event_time_utc="2026-07-21T00:02:00Z",
        reason="c",
        verdict=OQ_VERDICT_QUALIFIED,
        **_TERMINAL,
    )
    # A second terminal (or any) append is refused -- the qualification is consumed.
    with pytest.raises(OQRegistryError, match="terminal"):
        append_oq_event(
            p,
            identity=IDENT,
            event=OQ_EVENT_FAILED,
            event_time_utc="2026-07-21T00:03:00Z",
            reason="again",
            failure_description="rerun",
        )


# --------------------------------------------------------------------------- #
# Shared-identity drift + terminal-field shape                                #
# --------------------------------------------------------------------------- #
def test_shared_identity_drift_between_events(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    drifted = replace(IDENT, fixture_sha256="9" * 64)
    s = build_oq_event(
        identity=drifted,
        event=OQ_EVENT_STARTED,
        event_time_utc="2026-07-21T00:00:01+00:00",
        event_ordinal=1,
        reason="s",
        prev_hash=r.entry_hash,
    )
    _write(p, r, s)
    with pytest.raises(OQRegistryError, match="shared identity drifted"):
        read_oq_registry(p)


def test_completed_with_failure_description_refused() -> None:
    with pytest.raises(OQRegistryError, match="must not carry a failure description"):
        build_oq_event(
            identity=IDENT,
            event=OQ_EVENT_COMPLETED,
            event_time_utc="2026-07-21T00:00:00Z",
            event_ordinal=2,
            reason="c",
            prev_hash="0" * 64,
            verdict=OQ_VERDICT_QUALIFIED,
            failure_description="oops",
            **_TERMINAL,
        )


def test_failed_with_success_hashes_refused() -> None:
    with pytest.raises(OQRegistryError, match="must not carry"):
        build_oq_event(
            identity=IDENT,
            event=OQ_EVENT_FAILED,
            event_time_utc="2026-07-21T00:00:00Z",
            event_ordinal=2,
            reason="f",
            prev_hash="0" * 64,
            failure_description="x",
            **_TERMINAL,
        )


def test_registered_with_terminal_hash_refused() -> None:
    with pytest.raises(OQRegistryError, match="must not carry"):
        build_oq_event(
            identity=IDENT,
            event=OQ_EVENT_REGISTERED,
            event_time_utc="2026-07-21T00:00:00Z",
            event_ordinal=0,
            reason="r",
            prev_hash="0" * 64,
            result_sha256="1" * 64,
        )


def test_completed_bad_verdict_refused() -> None:
    with pytest.raises((OQRegistryError, ValueError), match="verdict"):
        build_oq_event(
            identity=IDENT,
            event=OQ_EVENT_COMPLETED,
            event_time_utc="2026-07-21T00:00:00Z",
            event_ordinal=2,
            reason="c",
            prev_hash="0" * 64,
            verdict="totally_qualified",
            **_TERMINAL,
        )


def test_oversized_failure_description_refused() -> None:
    with pytest.raises(OQRegistryError, match="size bound"):
        build_oq_event(
            identity=IDENT,
            event=OQ_EVENT_FAILED,
            event_time_utc="2026-07-21T00:00:00Z",
            event_ordinal=2,
            reason="f",
            prev_hash="0" * 64,
            failure_description="x" * (MAX_FAILURE_DESCRIPTION_CHARS + 1),
        )


# --------------------------------------------------------------------------- #
# Chain / ordinal / strict-parse attacks (tamper the committed bytes)         #
# --------------------------------------------------------------------------- #
def _tamper_last(path: Path, **changes: object) -> None:
    lines = path.read_bytes().splitlines()
    obj = json.loads(lines[-1])
    obj.update(changes)
    lines[-1] = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")


def test_broken_prev_hash(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, prev_hash="0" * 64)  # breaks chain (and entry_hash)
    with pytest.raises(OQRegistryError):
        read_oq_registry(p)


def test_skipped_ordinal(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    r = _built(GENESIS_PREV_HASH, OQ_EVENT_REGISTERED, 0)
    s = _built(r.entry_hash, OQ_EVENT_STARTED, 5)  # ordinal 5 at index 1
    _write(p, r, s)
    with pytest.raises(OQRegistryError, match="out of order"):
        read_oq_registry(p)


def test_symlink_registry_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    link = tmp_path / "link.jsonl"
    link.symlink_to(p)
    with pytest.raises(OQRegistryError, match="symlink"):
        read_oq_registry(link)


def test_bool_ordinal_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, event_ordinal=True)
    with pytest.raises((OQRegistryError, ValueError)):
        read_oq_registry(p)


def test_naive_timestamp_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, event_time_utc="2026-07-21T00:00:00")  # no offset
    with pytest.raises(OQRegistryError):
        read_oq_registry(p)


def test_non_utc_offset_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, event_time_utc="2026-07-21T00:00:00-05:00")
    with pytest.raises(OQRegistryError):
        read_oq_registry(p)


def test_duplicate_json_key_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    line = p.read_bytes().splitlines()[-1]
    poisoned = line[:-1] + b',"reason":"dup"}'  # a second reason key
    p.write_bytes(poisoned + b"\n")
    with pytest.raises((OQRegistryError, ValueError)):
        read_oq_registry(p)


def test_unknown_key_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, sneaky="x")
    with pytest.raises((OQRegistryError, ValueError)):
        read_oq_registry(p)


def test_tampered_entry_hash_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, reason="tampered-body")  # entry_hash no longer matches body
    with pytest.raises(OQRegistryError, match="entry_hash does not match"):
        read_oq_registry(p)


def test_oversized_line_refused(tmp_path: Path) -> None:
    p = tmp_path / "reg.jsonl"
    _valid_completed(p)
    _tamper_last(p, reason="x" * 9000)
    with pytest.raises(OQRegistryError, match="max line size"):
        read_oq_registry(p)
