"""V2C sections 6 + 10: the offline operational-qualification PROTOCOL + cash-control identity.

Declares *what the qualification is* as a set of pure, self-digesting governance artifacts, fixed
before the qualification is registered (OQ-R) or executed (OQ-P). Five artifacts, each a function of
the frozen qualification source and the firewall's live behaviour:

* the **cash-control operational identity** (section 10) -- the zero-exposure invariant vector the
  one admissible operational target must satisfy, cross-checked against the live firewall so the
  identity cannot drift from what the firewall actually admits/refuses;
* the deterministic **fault schedule** -- the per-slot fault taxonomy the synthetic stream injects,
  declared as an auditable ordered rule table and *proven* to reproduce the live schedule slot for
  slot;
* the materialized **synthetic fixture manifest** -- ETH and BTC, at least ``OQ_MIN_EVENT_SLOTS``
  daily slots each, bound to the actual accepted bar stream by hash (not merely by summary counts);
* the **SLO / qualification-criteria contract** -- the ordered criteria and the governing
  "holds for every instrument" pass rule; and
* the **protocol methodology** -- the identity, run parameters, the zero-exposure invariants, and
  the ordered criteria, whose aggregate digest binds the four sub-artifacts by content hash. The
  registry binds this protocol digest at OQ-R.

``verify_*`` re-derives each artifact from source and refuses drift; ``verify_oq_protocol_bundle``
verifies all five reproduce byte-for-byte. Nothing here evaluates a strategy, reads market data, or
computes market performance -- the protocol *pins the zero-exposure invariant the run must satisfy*
and hashes source/behaviour only. The manifests live under ``governance/v2c/`` -- outside the frozen
``research/``/``release/`` roots -- so they add evidence without touching the frozen stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.shadow.domain import InstrumentId
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from eth_research.v2c.firewall import (
    ALLOWED_REQUEST_KINDS,
    CASH_CONTROL_TARGET_ID,
    FORBIDDEN_REQUEST_KINDS,
    KNOWN_LEGACY_CANDIDATE_IDS,
    CashControlIntent,
    V2CFirewallError,
    guard_request_kind,
    resolve_operational_target,
)
from eth_research.v2c.oq.events import (
    FAULT_CLASSES,
    FAULT_CONFLICTING_DUPLICATE,
    FAULT_DELAYED_RECEIVE,
    FAULT_DUPLICATE,
    FAULT_GAP,
    FAULT_HIGH_VOLATILITY,
    FAULT_NORMAL,
    FAULT_OUT_OF_ORDER,
    FAULT_STALE,
    FAULT_ZERO_VOLUME,
    OQ_FIXTURE_COHORT_START,
    OQ_INTERVAL_SECONDS,
    OQ_MIN_ACCEPTED_EVENTS,
    OQ_MIN_EVENT_SLOTS,
    _fault_for_slot,
    build_synthetic_raw_events,
    fixture_manifest,
    ingest_events,
)
from eth_research.v2c.oq.harness import (
    DEFAULT_INSTRUMENTS,
    DEFAULT_MAX_DRAWDOWN_FRACTION,
    DEFAULT_STALENESS_SECONDS,
    DEFAULT_STARTING_CASH,
)
from eth_research.v2c.oq.slo import QUALIFICATION_CRITERIA

# --- identity ---------------------------------------------------------------
#: The methodology and the single, deliberate qualification-run identity.
OQ_METHODOLOGY_ID: str = "v2c_offline_operational_qualification"
OQ_QUALIFICATION_ID: str = "v2c_offline_operational_qualification_run_001"

#: The instruments the qualification exercises, each as a separate single-instrument run.
OQ_PROTOCOL_INSTRUMENTS: tuple[str, ...] = DEFAULT_INSTRUMENTS

#: The declared slot count the fixture materializes (comfortably above ``OQ_MIN_EVENT_SLOTS``).
OQ_PROTOCOL_SLOTS: int = 3800

OQ_PROTOCOL_SCHEMA_VERSION: int = 1

# --- committed artifact locations (governance, not a frozen root) -----------
OQ_PROTOCOL_RELPATH: str = "governance/v2c/oq_protocol.json"
OQ_CASH_CONTROL_IDENTITY_RELPATH: str = "governance/v2c/oq_cash_control_identity.json"
OQ_FAULT_SCHEDULE_RELPATH: str = "governance/v2c/oq_fault_schedule.json"
OQ_FIXTURE_MANIFEST_RELPATH: str = "governance/v2c/oq_fixture_manifest.json"
OQ_SLO_CONTRACT_RELPATH: str = "governance/v2c/oq_slo_contract.json"

#: The governing zero-exposure invariant every cash-control instant must satisfy. This is the
#: numeric contract the run is *required* to hold (requested and realized), stated once here so the
#: protocol, the runner, and the OQ-Q oracle all measure against the same vector.
OQ_ZERO_EXPOSURE_INVARIANT: dict[str, float | int] = {
    "requested_risky_target_weight": 0.0,
    "requested_notional": 0.0,
    "requested_fills": 0,
    "requested_turnover": 0.0,
    "approved_weight": 0.0,
    "risky_intent_count": 0,
    "fill_count": 0,
    "turnover": 0.0,
}

#: The deterministic fault schedule, declared as an ordered ``(modulus, remainder, fault)`` rule
#: table. The first matching rule wins; a slot matching none is ``normal``. Proven equal to the live
#: ``events._fault_for_slot`` slot-for-slot by :func:`build_oq_fault_schedule`.
_FAULT_SCHEDULE_RULES: tuple[tuple[int, int, str], ...] = (
    (500, 37, FAULT_OUT_OF_ORDER),
    (500, 53, FAULT_CONFLICTING_DUPLICATE),
    (500, 71, FAULT_DELAYED_RECEIVE),
    (250, 17, FAULT_DUPLICATE),
    (300, 29, FAULT_GAP),
    (400, 41, FAULT_STALE),
    (200, 11, FAULT_ZERO_VOLUME),
    (150, 7, FAULT_HIGH_VOLATILITY),
)

#: One-line meaning of each qualification criterion (keys must equal ``QUALIFICATION_CRITERIA``).
_CRITERION_DESCRIPTIONS: dict[str, str] = {
    "qualification_coverage": (
        "the run has at least one instrument and every instrument is covered by a resource report "
        "and a recovery report (no vacuous pass)"
    ),
    "event_acceptance_correctness": (
        "each accepted stream is strictly monotonic and unique; every rejection maps to its "
        "injected fault; every fault flag fires; the accepted floor is met"
    ),
    "duplicate_suppression": "exact duplicates are suppressed on every instrument",
    "conflicting_duplicate_detection": (
        "same-time different-bar events are rejected and alerted one-for-one"
    ),
    "journal_durability": "the append-only journal is durable and hash-chained",
    "checkpoint_consistency": "checkpoints are consistent with the journal",
    "recovery_idempotency": "restart/recovery is deterministic and idempotent",
    "kill_switch_trip_latency": "the kill switch trips within its drilled latency bound",
    "alert_completeness": "every runner alert is journaled",
    "state_reconstruction": "journal and checkpoint reconstruct the state exactly",
    "bounded_processing_memory": "processing and memory stay within deterministic bounds",
    "zero_risky_exposure": (
        "every fill and intent is exactly zero exposure/notional/turnover; the book stays 100% "
        "cash; no exposure-driven kill trip"
    ),
}

_PROTOCOL_STATEMENT = (
    "The V2C offline operational qualification exercises the candidate-free cash_control target "
    "through the shadow platform under a deterministic synthetic ETH/BTC event stream carrying a "
    "full fault taxonomy, in virtual time. It resolves no strategy, reads no market data, and "
    "computes no return, equity, or market-performance metric. Its governing invariant is exactly "
    "zero risky exposure: every requested and realized exposure, notional, fill count, and "
    "turnover is zero, and the paper book holds 100% cash throughout."
)


class OQProtocolError(V2ValidationError):
    """A committed OQ protocol artifact drifted from the live qualification source/behaviour."""


def _read_bytes(repo_root: Path, relpath: str) -> bytes:
    raw = repo_root / relpath
    if raw.is_symlink():
        raise OQProtocolError(f"{relpath} is a symlink")
    path = raw.resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise OQProtocolError(f"{relpath} escapes the repository root")
    if not path.is_file():
        raise OQProtocolError(f"{relpath} is missing")
    return path.read_bytes()


# --------------------------------------------------------------------------- #
# Section 10: the cash-control operational identity                           #
# --------------------------------------------------------------------------- #
def _cross_check_firewall() -> None:
    """Prove the live firewall admits only ``cash_control`` at exactly zero exposure and refuses
    every legacy candidate id and forbidden request kind, so the identity artifact cannot claim a
    guarantee the firewall does not actually enforce."""
    if CASH_CONTROL_TARGET_ID != "cash_control":
        raise OQProtocolError("firewall cash-control target id drifted from 'cash_control'")
    if set(ALLOWED_REQUEST_KINDS) != {"cash_control_operation"}:
        raise OQProtocolError("firewall admits a request kind other than cash_control_operation")
    if guard_request_kind("cash_control_operation") != "cash_control_operation":
        raise OQProtocolError("firewall did not admit cash_control_operation")
    target = resolve_operational_target(CASH_CONTROL_TARGET_ID)
    if target.target_id != CASH_CONTROL_TARGET_ID:
        raise OQProtocolError("resolved operational target is not cash_control")
    intent = CashControlIntent.zero(OQ_FIXTURE_COHORT_START)
    if (
        intent.risky_target_weight != 0.0
        or intent.requested_notional != 0.0
        or intent.requested_fills != 0
        or intent.requested_turnover != 0.0
    ):
        raise OQProtocolError("cash_control intent is not exactly zero exposure")
    for candidate_id in KNOWN_LEGACY_CANDIDATE_IDS:
        try:
            resolve_operational_target(candidate_id)
        except V2CFirewallError:
            continue
        raise OQProtocolError(f"firewall failed to refuse legacy candidate id {candidate_id!r}")
    for kind in sorted(FORBIDDEN_REQUEST_KINDS):
        try:
            guard_request_kind(kind)
        except V2CFirewallError:
            continue
        raise OQProtocolError(f"firewall failed to refuse forbidden request kind {kind!r}")


def build_oq_cash_control_identity() -> dict[str, Any]:
    """Derive the cash-control operational identity, cross-checked against the live firewall."""
    _cross_check_firewall()
    body: dict[str, Any] = {
        "schema_version": OQ_PROTOCOL_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_cash_control_identity",
        "target_id": CASH_CONTROL_TARGET_ID,
        "is_strategy": False,
        "reads_market_data_for_decision": False,
        "zero_exposure_invariant": dict(sorted(OQ_ZERO_EXPOSURE_INVARIANT.items())),
        "allowed_request_kinds": sorted(ALLOWED_REQUEST_KINDS),
        "forbidden_request_kinds": sorted(FORBIDDEN_REQUEST_KINDS),
        "refused_legacy_candidate_ids": sorted(KNOWN_LEGACY_CANDIDATE_IDS),
        "statement": (
            "cash_control is the only operational target V2C resolves. It is not a strategy: it "
            "references no candidate, makes no market-data-driven decision, and every intent it "
            "emits requests exactly zero risky exposure, notional, fills, and turnover."
        ),
    }
    body["identity_digest"] = canonical_sha256(body)
    return body


# --------------------------------------------------------------------------- #
# The deterministic fault schedule                                            #
# --------------------------------------------------------------------------- #
def _scheduled_fault(index: int) -> str:
    for modulus, remainder, fault in _FAULT_SCHEDULE_RULES:
        if index % modulus == remainder:
            return fault
    return FAULT_NORMAL


def build_oq_fault_schedule(*, slots: int = OQ_PROTOCOL_SLOTS) -> dict[str, Any]:
    """Derive the fault-schedule artifact and prove the declared rule table reproduces the live
    ``events._fault_for_slot`` schedule for every slot in ``[0, slots)``."""
    fault_vector: list[str] = []
    counts: dict[str, int] = dict.fromkeys(sorted(FAULT_CLASSES), 0)
    for index in range(slots):
        declared = _scheduled_fault(index)
        live = _fault_for_slot(index)
        if declared != live:
            raise OQProtocolError(
                f"declared fault schedule diverges from live source at slot {index}: "
                f"{declared!r} != {live!r}"
            )
        fault_vector.append(declared)
        counts[declared] += 1
    body: dict[str, Any] = {
        "schema_version": OQ_PROTOCOL_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_fault_schedule",
        "slots": slots,
        "rules": [
            {"modulus": modulus, "remainder": remainder, "fault": fault}
            for modulus, remainder, fault in _FAULT_SCHEDULE_RULES
        ],
        "default_fault": FAULT_NORMAL,
        "fault_classes": sorted(FAULT_CLASSES),
        "scheduled_fault_counts": counts,
        # Bind the *actual* per-slot fault sequence, not merely the summary counts.
        "fault_vector_sha256": sha256_bytes("\n".join(fault_vector).encode("utf-8")),
    }
    body["fault_schedule_digest"] = canonical_sha256(body)
    return body


# --------------------------------------------------------------------------- #
# The materialized synthetic fixture manifest (ETH + BTC)                      #
# --------------------------------------------------------------------------- #
def _instrument_fixture(symbol: str, *, slots: int) -> dict[str, Any]:
    instrument = InstrumentId(symbol)
    raw = build_synthetic_raw_events(instrument, slots=slots)
    acceptance = ingest_events(raw)
    manifest = fixture_manifest(raw, acceptance, slots=slots)
    # Bind the actual accepted bar stream by hash, so a fixture with matching summary counts but a
    # different bar sequence cannot masquerade as this one.
    accepted_stream_sha256 = sha256_bytes(
        b"".join(canonical_json_bytes(env.to_canonical()) for env in acceptance.accepted)
    )
    return {**manifest, "accepted_stream_sha256": accepted_stream_sha256}


def build_oq_fixture_manifest(*, slots: int = OQ_PROTOCOL_SLOTS) -> dict[str, Any]:
    """Derive the materialized fixture manifest for every protocol instrument (ETH + BTC)."""
    if slots < OQ_MIN_EVENT_SLOTS:
        raise OQProtocolError(f"fixture slots {slots} < minimum {OQ_MIN_EVENT_SLOTS}")
    instruments = {
        symbol: _instrument_fixture(symbol, slots=slots)
        for symbol in sorted(OQ_PROTOCOL_INSTRUMENTS)
    }
    body: dict[str, Any] = {
        "schema_version": OQ_PROTOCOL_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_fixture_manifest",
        "cohort_start": OQ_FIXTURE_COHORT_START,
        "interval_seconds": OQ_INTERVAL_SECONDS,
        "slots": slots,
        "min_event_slots": OQ_MIN_EVENT_SLOTS,
        "min_accepted_events": OQ_MIN_ACCEPTED_EVENTS,
        "instruments": instruments,
    }
    body["fixture_digest"] = canonical_sha256(body)
    return body


# --------------------------------------------------------------------------- #
# The SLO / qualification-criteria contract                                   #
# --------------------------------------------------------------------------- #
def build_oq_slo_contract() -> dict[str, Any]:
    """Derive the SLO contract: the ordered criteria + the 'every instrument' pass rule."""
    if tuple(_CRITERION_DESCRIPTIONS) != QUALIFICATION_CRITERIA:
        raise OQProtocolError("SLO criterion descriptions drifted from QUALIFICATION_CRITERIA")
    body: dict[str, Any] = {
        "schema_version": OQ_PROTOCOL_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_slo_contract",
        "criteria": list(QUALIFICATION_CRITERIA),
        "criterion_descriptions": dict(_CRITERION_DESCRIPTIONS),
        "pass_rule": "a criterion passes only if it holds for every instrument; the verdict "
        "passes only if every criterion passes",
        "computes_market_performance": False,
        "min_event_slots": OQ_MIN_EVENT_SLOTS,
        "min_accepted_events": OQ_MIN_ACCEPTED_EVENTS,
    }
    body["slo_contract_digest"] = canonical_sha256(body)
    return body


# --------------------------------------------------------------------------- #
# The protocol methodology (binds the four sub-artifacts by content hash)      #
# --------------------------------------------------------------------------- #
def build_oq_protocol(*, slots: int = OQ_PROTOCOL_SLOTS) -> dict[str, Any]:
    """Derive the protocol methodology, binding the four sub-artifacts by their content hash.

    A pure function of the frozen qualification source and the firewall's live behaviour: it builds
    each sub-artifact fresh and embeds its canonical SHA-256, which equals the committed file's byte
    hash. The registry binds ``protocol_digest`` (and the four sub-artifact hashes) at OQ-R.
    """
    identity = build_oq_cash_control_identity()
    fault_schedule = build_oq_fault_schedule(slots=slots)
    fixture = build_oq_fixture_manifest(slots=slots)
    slo_contract = build_oq_slo_contract()
    body: dict[str, Any] = {
        "schema_version": OQ_PROTOCOL_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_protocol",
        "methodology_id": OQ_METHODOLOGY_ID,
        "qualification_id": OQ_QUALIFICATION_ID,
        "package_version": PACKAGE_VERSION,
        "statement": _PROTOCOL_STATEMENT,
        "instruments": sorted(OQ_PROTOCOL_INSTRUMENTS),
        "parameters": {
            "slots": slots,
            "starting_cash": DEFAULT_STARTING_CASH,
            "interval_seconds": OQ_INTERVAL_SECONDS,
            "cohort_start": OQ_FIXTURE_COHORT_START,
            "staleness_seconds": DEFAULT_STALENESS_SECONDS,
            "max_drawdown_fraction": DEFAULT_MAX_DRAWDOWN_FRACTION,
            "min_event_slots": OQ_MIN_EVENT_SLOTS,
            "min_accepted_events": OQ_MIN_ACCEPTED_EVENTS,
        },
        "zero_exposure_invariant": dict(sorted(OQ_ZERO_EXPOSURE_INVARIANT.items())),
        "criteria": list(QUALIFICATION_CRITERIA),
        "cash_control_identity_sha256": canonical_sha256(identity),
        "fault_schedule_sha256": canonical_sha256(fault_schedule),
        "fixture_sha256": canonical_sha256(fixture),
        "slo_contract_sha256": canonical_sha256(slo_contract),
    }
    body["protocol_digest"] = canonical_sha256(body)
    return body


# --------------------------------------------------------------------------- #
# Render / write / verify (per artifact + bundle)                             #
# --------------------------------------------------------------------------- #
def render_artifact_bytes(artifact: dict[str, Any]) -> bytes:
    """Serialize an artifact dict to canonical JSON bytes (sorted keys, trailing newline)."""
    return canonical_json_bytes(artifact)


#: (relpath, builder) for each committed artifact, in dependency order (protocol last).
_ARTIFACTS: tuple[tuple[str, Any], ...] = (
    (OQ_CASH_CONTROL_IDENTITY_RELPATH, build_oq_cash_control_identity),
    (OQ_FAULT_SCHEDULE_RELPATH, build_oq_fault_schedule),
    (OQ_FIXTURE_MANIFEST_RELPATH, build_oq_fixture_manifest),
    (OQ_SLO_CONTRACT_RELPATH, build_oq_slo_contract),
    (OQ_PROTOCOL_RELPATH, build_oq_protocol),
)


def committed_artifact_sha256(repo_root: str | Path, relpath: str) -> str:
    """The SHA-256 of a committed artifact's bytes (what OQ-R binds into the registry identity)."""
    return sha256_bytes(_read_bytes(Path(repo_root), relpath))


def write_oq_protocol_bundle(repo_root: str | Path) -> tuple[Path, ...]:
    """(Re)write all five committed protocol artifacts from live source; return their paths."""
    root = Path(repo_root)
    written: list[Path] = []
    for relpath, builder in _ARTIFACTS:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_artifact_bytes(builder()))
        written.append(path)
    return tuple(written)


def verify_oq_protocol_bundle(repo_root: str | Path) -> None:
    """Every committed protocol artifact must reproduce byte-for-byte from the live source."""
    root = Path(repo_root)
    for relpath, builder in _ARTIFACTS:
        committed = _read_bytes(root, relpath)
        fresh = render_artifact_bytes(builder())
        if committed != fresh:
            raise OQProtocolError(
                f"committed {relpath} does not reproduce from live source "
                "(qualification protocol/source changed)"
            )


def oq_protocol_digest(*, slots: int = OQ_PROTOCOL_SLOTS) -> str:
    """The aggregate protocol digest (bound by OQ-R at registration)."""
    digest = build_oq_protocol(slots=slots)["protocol_digest"]
    assert isinstance(digest, str)
    return digest


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2C OQ protocol bundle (read-only verify)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true", help="(re)write the protocol artifacts")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.write:
        for path in write_oq_protocol_bundle(root):
            print(f"wrote {path}")
        return 0
    try:
        verify_oq_protocol_bundle(root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "OQ_CASH_CONTROL_IDENTITY_RELPATH",
    "OQ_FAULT_SCHEDULE_RELPATH",
    "OQ_FIXTURE_MANIFEST_RELPATH",
    "OQ_METHODOLOGY_ID",
    "OQ_PROTOCOL_INSTRUMENTS",
    "OQ_PROTOCOL_RELPATH",
    "OQ_PROTOCOL_SCHEMA_VERSION",
    "OQ_PROTOCOL_SLOTS",
    "OQ_QUALIFICATION_ID",
    "OQ_SLO_CONTRACT_RELPATH",
    "OQ_ZERO_EXPOSURE_INVARIANT",
    "OQProtocolError",
    "build_oq_cash_control_identity",
    "build_oq_fault_schedule",
    "build_oq_fixture_manifest",
    "build_oq_protocol",
    "build_oq_slo_contract",
    "committed_artifact_sha256",
    "oq_protocol_digest",
    "render_artifact_bytes",
    "verify_oq_protocol_bundle",
    "write_oq_protocol_bundle",
]
