"""The V2D growable cohort surface — how frozen M3F verification admits growth.

M3F froze the accepted M2B-M3E stack as a *static* byte-anchored catalog: at
acceptance the prospective cohort had exactly its genesis rows, zero production
proposals, and a read-only standing workflow. The separately governed V2D
milestone changes exactly that premise: the committed activation anchor
(``governance/v2d/prospective_activation.json``) authorizes DATA-ONLY growth of
the prospective cohort through reviewed, append-only update proposals.

This module defines the supersession **lattice** every M3F verifier applies:

* **no growth evidence** → every check runs exactly as accepted (byte-static);
* **growth evidence + a valid committed anchor** → the enumerated growable
  surface verifies **append-only against the accepted baseline** (frozen bytes
  must survive as an exact prefix; replaced snapshots are delegated to their
  own milestone verifiers with monotone floors), while every non-growable byte
  stays anchored exactly;
* **growth evidence without a valid anchor** → fail closed, as before.

The anchor's byte-level authority lives in ``eth_research.v2d`` (pure-constant
byte identity) and the Fable 5 governed-artifact inventory; this isolated
verifier still re-checks the anchor strictly — canonical bytes, kind, schema,
self-hash (the ``m3d/<domain>``-prefixed canonical digest), authorized workflow
and repository — through its own primitives, importing nothing from the layers
it verifies.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_int,
    require_mapping,
    require_str,
    strict_jsonl_records,
)

V2D_ANCHOR_RELPATH = "governance/v2d/prospective_activation.json"
_ANCHOR_KIND = "v2d_prospective_activation"
_ANCHOR_DOMAIN_PREFIX = b"m3d/v2d_prospective_activation_anchor\n"
_AUTHORIZED_WORKFLOW = "m3e-prospective-update.yml"
_AUTHORIZED_REPOSITORY = "panfot1409/gambling-winnings"

#: Append-only chained ledgers: the accepted bytes must remain an exact prefix.
GROWABLE_APPEND_CHAINS: tuple[str, ...] = (
    "research/m3d/prospective_segments.jsonl",
    "research/m3e/proposal_registry.jsonl",
)
#: Replaced snapshots of the growing cohort: byte-stasis is delegated to their
#: milestone verifiers (rebuild-from-raw-bytes) plus the expected-state floors.
GROWABLE_CURRENT_STATE: tuple[str, ...] = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
)
#: New evidence the reviewed update path creates (absent at M3F acceptance).
#: The acceptance chain (registry + per-proposal acceptance/completion records)
#: is itself part of the lawful growth surface: it is what makes a landed
#: proposal legal, and it is verified strictly by :func:`read_acceptance_state`.
GROWABLE_NEW_FILES: tuple[str, ...] = (
    "research/m3d/update_attempts.jsonl",
    "research/m3e/acceptance_registry.jsonl",
)
GROWABLE_NEW_PATH_PREFIXES: tuple[str, ...] = (
    "research/m3e/proposals/",
    "research/m3e/acceptances/",
    "research/m3d/raw/coinbase/coinbase-eth-usd-prospective-update-",
)

GROWABLE_PATHS: frozenset[str] = frozenset(
    (*GROWABLE_APPEND_CHAINS, *GROWABLE_CURRENT_STATE, *GROWABLE_NEW_FILES)
)


def is_growable_new_path(relpath: str) -> bool:
    """A path the reviewed update path may create after M3F acceptance."""
    return relpath in GROWABLE_NEW_FILES or relpath.startswith(GROWABLE_NEW_PATH_PREFIXES)


def is_growable_path(relpath: str) -> bool:
    return relpath in GROWABLE_PATHS or is_growable_new_path(relpath)


def v2d_activation_anchor_active(repo_root: str | Path) -> bool:
    """True only for a strictly-valid committed V2D activation anchor.

    Absent file → not active (never an error: absence simply means the static
    accepted state governs). A present-but-invalid anchor raises — a malformed
    or tampered authorization must never silently degrade to either mode.
    """
    path = Path(repo_root) / V2D_ANCHOR_RELPATH
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise M3FValidationError(f"{V2D_ANCHOR_RELPATH} is not a regular file")
    doc = require_mapping(load_canonical_json(path.read_bytes(), "v2d_anchor"), "v2d_anchor")
    if doc.get("kind") != _ANCHOR_KIND or doc.get("schema_version") != 1:
        raise M3FValidationError("activation anchor kind/schema is not the V2D anchor")
    body: dict[str, Any] = {k: v for k, v in doc.items() if k != "anchor_sha256"}
    expected = hashlib.sha256(_ANCHOR_DOMAIN_PREFIX + canonical_json_bytes(body)).hexdigest()
    if require_str(doc.get("anchor_sha256"), "anchor_sha256") != expected:
        raise M3FValidationError("activation anchor self-hash does not match its content")
    mechanism = require_mapping(doc.get("mechanism"), "anchor.mechanism")
    if require_str(mechanism.get("workflow_basename"), "workflow_basename") != _AUTHORIZED_WORKFLOW:
        raise M3FValidationError("activation anchor authorizes an unexpected workflow")
    if require_str(mechanism.get("repository"), "repository") != _AUTHORIZED_REPOSITORY:
        raise M3FValidationError("activation anchor authorizes an unexpected repository")
    return True


def require_exact_prefix(baseline: bytes, live: bytes, label: str) -> None:
    """Fail closed unless the accepted baseline bytes survive as an exact prefix."""
    if len(live) < len(baseline) or live[: len(baseline)] != baseline:
        raise M3FValidationError(
            f"{label}: accepted baseline bytes are not an exact prefix of the live file "
            "(append-only growth violated)"
        )


# ---------------------------------------------------------------------------
# The V2E acceptance chain — M3F's own strict, import-isolated reader.
#
# The M3E layer WRITES the acceptance evidence (``eth_research.m3e.acceptance``);
# this verifier re-implements the read side from scratch (chain walk, self-hash,
# genesis triple-check) so the layer under audit never verifies itself. A grown
# tree is lawful only when a valid V2D anchor exists AND every committed
# production proposal is covered by a verified acceptance record; the exact
# expected bytes of the transitioned cohort files are the genesis pins overlaid
# by the ordered chain — never "whatever is newer".
# ---------------------------------------------------------------------------

ACCEPTANCE_REGISTRY_RELPATH = "research/m3e/acceptance_registry.jsonl"
ACCEPTANCES_ROOT_RELPATH = "research/m3e/acceptances"
_ACCEPTANCE_RECORD_PREFIX = b"m3d/m3e/proposal_acceptance_record\n"
_ACCEPTANCE_COMPLETION_PREFIX = b"m3d/m3e/proposal_acceptance_completion\n"

#: Pre-existing cohort files every acceptance transitions (old -> new byte pins).
ACCEPTANCE_TRANSITIONED_PATHS: tuple[str, ...] = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/prospective_segments.jsonl",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
    "research/m3e/proposal_registry.jsonl",
)

#: Independently byte-frozen tables that pin the pre-acceptance state; the chain
#: genesis must agree with every one that is present, and at least one must be
#: present (both exist in a full checkout; the recovery capsule carries them as
#: governance evidence). The M3F freeze catalog is deliberately NOT an authority:
#: it is rebuilt at re-registration and snapshots the *current* state.
ACCEPTANCE_GENESIS_AUTHORITIES: tuple[str, ...] = (
    "docs/M3C_M3E_STACK_FREEZE_TABLE.json",
    "research/v2ab/stack_freeze_table.json",
)


@dataclasses.dataclass(frozen=True)
class AcceptanceView:
    """The verified acceptance chain, reduced to what M3F verifiers consume."""

    accepted_ids: tuple[str, ...]
    expected_state: dict[str, str]
    created: dict[str, str]

    @property
    def count(self) -> int:
        return len(self.accepted_ids)


def _authority_pins(root: Path, relpath: str) -> dict[str, str]:
    doc = require_mapping(load_canonical_json((root / relpath).read_bytes(), relpath), relpath)
    rows: list[Any] | None = None
    for key in ("files", "artifacts", "entries"):
        if key in doc:
            rows = list(doc[key])
            break
    if rows is None:
        raise M3FValidationError(f"{relpath}: unrecognized freeze-table shape")
    wanted = set(ACCEPTANCE_TRANSITIONED_PATHS)
    pins: dict[str, str] = {}
    for raw in rows:
        row = require_mapping(raw, f"{relpath} row")
        path = require_str(row.get("path"), "path")
        if path in wanted:
            pins[path] = require_str(row.get("sha256"), "sha256")
    if set(pins) != wanted:
        raise M3FValidationError(f"{relpath}: missing pre-acceptance pins")
    return pins


def _genesis_pins(root: Path) -> dict[str, str]:
    first: dict[str, str] | None = None
    found = 0
    for relpath in ACCEPTANCE_GENESIS_AUTHORITIES:
        path = root / relpath
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise M3FValidationError(f"{relpath} is not a regular file")
        found += 1
        pins = _authority_pins(root, relpath)
        if first is None:
            first = pins
        elif pins != first:
            raise M3FValidationError(
                f"pre-acceptance pins disagree between authorities (at {relpath})"
            )
    if first is None or found == 0:
        raise M3FValidationError(
            "no genesis authority table is present; cannot anchor the acceptance chain"
        )
    return first


def _self_hashed_body(
    doc: dict[str, Any], *, field: str, prefix: bytes, label: str
) -> dict[str, Any]:
    body = {k: v for k, v in doc.items() if k != field}
    expected = hashlib.sha256(prefix + canonical_json_bytes(body)).hexdigest()
    if require_str(doc.get(field), field) != expected:
        raise M3FValidationError(f"{label}: self-hash does not match its content")
    return body


def read_acceptance_state(repo_root: str | Path) -> AcceptanceView | None:
    """Strictly verify and reduce the acceptance chain (``None`` if absent).

    Absence is only lawful for a tree with zero production proposals — that
    cross-check belongs to the callers (honest state, oracles), which hard-stop
    on any uncovered proposal exactly as they did before acceptances existed.
    """
    root = Path(repo_root)
    registry = root / ACCEPTANCE_REGISTRY_RELPATH
    if not registry.exists():
        return None
    if registry.is_symlink() or not registry.is_file():
        raise M3FValidationError(f"{ACCEPTANCE_REGISTRY_RELPATH} is not a regular file")
    raw = registry.read_bytes()
    records = strict_jsonl_records(raw, "acceptance_registry")
    lines = raw.decode("utf-8").splitlines()
    if len(lines) != len(records) or not records:
        raise M3FValidationError("acceptance registry line/record mismatch or empty")
    prev = hashlib.sha256(b"").hexdigest()
    for line, record in zip(lines, records, strict=True):
        mapping = require_mapping(record, "acceptance registry record")
        if require_str(mapping.get("previous_line_sha256"), "previous_line_sha256") != prev:
            raise M3FValidationError("acceptance registry hash chain is broken")
        prev = hashlib.sha256(line.encode("utf-8")).hexdigest()

    genesis = require_mapping(records[0], "acceptance genesis")
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != "m3e_acceptance_registry":
        raise M3FValidationError("acceptance registry genesis sentinel is malformed")
    pins = {
        str(k): str(v)
        for k, v in require_mapping(
            genesis.get("pre_acceptance_state"), "pre_acceptance_state"
        ).items()
    }
    if pins != _genesis_pins(root):
        raise M3FValidationError(
            "acceptance genesis pins do not match the byte-frozen authority tables"
        )
    declared = [str(a) for a in genesis.get("genesis_authorities", [])]
    if declared != list(ACCEPTANCE_GENESIS_AUTHORITIES):
        raise M3FValidationError(
            "acceptance genesis authority list does not match the enforced set"
        )

    accepted: list[str] = []
    expected = dict(pins)
    created: dict[str, str] = {}
    for position, raw_entry in enumerate(records[1:], start=1):
        entry = require_mapping(raw_entry, "acceptance entry")
        if entry.get("entry_kind") != "acceptance":
            raise M3FValidationError("acceptance registry carries an unknown entry kind")
        if entry.get("sequence") != position:
            raise M3FValidationError(
                "acceptance registry sequence is reordered, duplicated, or gapped"
            )
        proposal_id = require_str(entry.get("proposal_id"), "proposal_id")
        if proposal_id in accepted:
            raise M3FValidationError(f"proposal {proposal_id} accepted twice")
        record_dir = root / ACCEPTANCES_ROOT_RELPATH / proposal_id
        record_path = record_dir / "acceptance.json"
        if record_path.is_symlink() or not record_path.is_file():
            raise M3FValidationError(f"acceptance record for {proposal_id} is missing")
        record = require_mapping(
            load_canonical_json(record_path.read_bytes(), "acceptance record"),
            "acceptance record",
        )
        _self_hashed_body(
            record,
            field="acceptance_sha256",
            prefix=_ACCEPTANCE_RECORD_PREFIX,
            label=f"acceptance record {proposal_id}",
        )
        if record.get("acceptance_sha256") != entry.get("acceptance_sha256"):
            raise M3FValidationError(
                f"registry entry does not bind the committed record for {proposal_id}"
            )
        if record.get("proposal_id") != proposal_id or record.get("sequence") != position:
            raise M3FValidationError(f"acceptance record {proposal_id}: identity mismatch")
        previous = require_mapping(record.get("previous_accepted"), "previous_accepted")
        prior_state = {
            str(k): str(v)
            for k, v in require_mapping(previous.get("state"), "previous state").items()
        }
        if prior_state != expected:
            raise M3FValidationError(
                f"acceptance {proposal_id} does not chain from the prior accepted state"
            )
        new_accepted = require_mapping(record.get("new_accepted"), "new_accepted")
        new_state = {
            str(k): str(v)
            for k, v in require_mapping(new_accepted.get("state"), "new state").items()
        }
        if set(new_state) != set(ACCEPTANCE_TRANSITIONED_PATHS):
            raise M3FValidationError(
                f"acceptance {proposal_id}: new state must pin exactly the transitioned paths"
            )
        # Re-derive the record's arithmetic and its own safety assertions. Hashing
        # alone only proves self-consistency, so a coordinated reseal would pass;
        # a forged record must also be internally TRUE.
        prev_rows = require_int(previous.get("row_count"), "previous_accepted.row_count")
        new_rows = require_int(new_accepted.get("row_count"), "new_accepted.row_count")
        interval = require_mapping(record.get("append_interval"), "append_interval")
        appended = require_int(interval.get("row_count"), "append_interval.row_count")
        if appended < 1 or new_rows != prev_rows + appended or new_rows >= 365:
            raise M3FValidationError(
                f"acceptance {proposal_id}: row arithmetic is false or claims maturity"
            )
        proof = require_mapping(record.get("append_only_proof"), "append_only_proof")
        if proof.get("is_append_only") is not True:
            raise M3FValidationError(f"acceptance {proposal_id}: append-only proof not affirmative")
        for counter in ("prior_rows_changed", "prior_rows_deleted"):
            if require_int(proof.get(counter), counter) != 0:
                raise M3FValidationError(f"acceptance {proposal_id}: {counter} is non-zero")
        created_pins = require_mapping(new_accepted.get("created"), "new_accepted.created")
        if not created_pins:
            raise M3FValidationError(f"acceptance {proposal_id}: pins no created evidence")
        # The accepted proposal directory is a CLOSED set: an extra file smuggled in
        # after acceptance must fail here too, not only in the m3e verifier.
        proposal_dir = root / "research/m3e/proposals" / proposal_id
        if proposal_dir.is_dir():
            live = {
                p.relative_to(root).as_posix()
                for p in proposal_dir.rglob("*")
                if p.is_file() or p.is_symlink()
            }
            pinned = {p for p in created_pins if p.startswith("research/m3e/proposals/")}
            if live != pinned:
                raise M3FValidationError(
                    f"acceptance {proposal_id}: proposal directory is not a closed set"
                )
        # Two runners, byte-identical payloads, re-derived from the pinned hashes.
        runners = require_mapping(record.get("runner_evidence"), "runner_evidence")
        raw_sets = set()
        for rname, rbody in runners.items():
            body = require_mapping(rbody, f"runner_evidence.{rname}")
            raws = require_mapping(body.get("raw_response_sha256"), "raw_response_sha256")
            if not raws:
                raise M3FValidationError(f"acceptance {proposal_id}: runner {rname} pins no payload")
            raw_sets.add(tuple(sorted((str(k), str(v)) for k, v in raws.items())))
        if len(runners) < 2 or len(raw_sets) != 1:
            raise M3FValidationError(
                f"acceptance {proposal_id}: runners are missing or not byte-identical"
            )
        accepted_at = require_str(record.get("acceptance_time"), "acceptance_time")
        window_close = require_str(interval.get("last_open"), "append_interval.last_open")
        if accepted_at < window_close or accepted_at >= "2031-01-01T00:00:00Z":
            raise M3FValidationError(
                f"acceptance {proposal_id}: acceptance_time is outside the lawful window"
            )
        if record.get("proposal_head_commit") == record.get("expected_parent_commit"):
            raise M3FValidationError(
                f"acceptance {proposal_id}: proposal head equals its own expected parent"
            )
        for logical, facts in require_mapping(
            record.get("sealed_ledgers"), "sealed_ledgers"
        ).items():
            entry = require_mapping(facts, f"sealed_ledgers.{logical}")
            if require_int(entry.get("byte_count"), "byte_count") != 0:
                raise M3FValidationError(
                    f"acceptance {proposal_id}: sealed ledger {logical} claims bytes"
                )
        if record.get("evaluation_authorized") is not False:
            raise M3FValidationError(f"acceptance {proposal_id} claims evaluation authority")
        if record.get("maturity_state") != "immature":
            raise M3FValidationError(f"acceptance {proposal_id} claims a non-immature cohort")
        for name, value in require_mapping(
            record.get("governance_flags"), "governance_flags"
        ).items():
            if value is not False:
                raise M3FValidationError(f"acceptance {proposal_id}: governance flag {name} is set")
        completion_path = record_dir / "acceptance_completion.json"
        if completion_path.is_symlink() or not completion_path.is_file():
            raise M3FValidationError(
                f"acceptance {proposal_id} has no completion record (two-phase binding)"
            )
        completion = require_mapping(
            load_canonical_json(completion_path.read_bytes(), "acceptance completion"),
            "acceptance completion",
        )
        _self_hashed_body(
            completion,
            field="completion_sha256",
            prefix=_ACCEPTANCE_COMPLETION_PREFIX,
            label=f"completion {proposal_id}",
        )
        if (
            completion.get("acceptance_sha256") != record.get("acceptance_sha256")
            or completion.get("proposal_id") != proposal_id
        ):
            raise M3FValidationError(f"completion {proposal_id} does not bind its record")
        accepted.append(proposal_id)
        expected = new_state
        for path, sha in require_mapping(new_accepted.get("created"), "created").items():
            created[str(path)] = str(sha)

    acceptances_dir = root / ACCEPTANCES_ROOT_RELPATH
    if acceptances_dir.exists():
        on_disk = {p.name for p in acceptances_dir.iterdir() if p.is_dir()}
        if on_disk - set(accepted):
            raise M3FValidationError("acceptance directories exist outside the registry chain")
    return AcceptanceView(accepted_ids=tuple(accepted), expected_state=expected, created=created)
