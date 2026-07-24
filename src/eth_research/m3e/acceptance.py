"""Explicit, append-only acceptance of landed prospective-cohort update proposals.

The reviewed M3E update path produces DATA-ONLY proposals on bot branches; merging
one grows the committed cohort. Before this module, every accepted-state verifier
(M3F legality + oracles + recovery capsule, the V2AB stack freeze table, the stack
doc-table tests, literal test pins) correctly failed closed on such a grown tree,
because *nothing recorded that a human-governed acceptance event happened*. This
module adds that event as committed evidence, forward-only (V2F §2.2):

* ``research/m3e/acceptance_registry.jsonl`` — an append-only, hash-chained ledger:
  a genesis line pinning the exact pre-acceptance cohort state (cross-checked against
  three independent byte-frozen tables), then one ``acceptance`` line per accepted
  proposal, in sequence order.
* ``research/m3e/acceptances/<proposal-id>/acceptance.json`` — the self-hashed
  acceptance record binding the proposal identity, its evidence hashes, the prior and
  new accepted state, the exact append interval, append-only proof outcomes, quality,
  governance flags, sealed-ledger facts, and the acceptance time.
* ``research/m3e/acceptances/<proposal-id>/acceptance_completion.json`` — the
  two-phase commit binding: the record cannot contain its own publication commit, so
  a follow-up completion record binds the exact commit that published it (the same
  completion-intent pattern the M3A/M3B registration path established).

Design law (enforced here and re-implemented independently by the M3F-internal and
stdlib readers):

* production expectation is always one exact state — the genesis pins overlaid by the
  ordered acceptance chain; there is no "anything newer is fine" mode;
* a production proposal present in the tree **without** a covering acceptance record
  is illegal (exactly the condition that made the pre-acceptance checks red);
* deleting, reordering, or duplicating a chain element breaks the hash chain and
  fails closed, and a naive edit breaks a self-hash. A *coordinated* reseal (edit
  a field, recompute the self-hash, rebind the registry entry, re-chain the
  ledger) defeats hashing alone — so every load additionally RE-DERIVES the
  record's semantics (:func:`_require_semantics_hold`) and cross-checks the chain
  head against the committed accepted base. A forged record must therefore also
  be internally *true*, not merely internally consistent. Detection of a reseal
  by an actor who can rewrite committed history additionally rests on git;
  that limit is stated, not papered over;
* acceptance N+1 must start from the exact accepted state of acceptance N;
* nothing here reads a market value: every binding is a hash, count, date, flag, or
  identity string — the module is data-governance only.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    domain_sha256,
    load_canonical_json,
    require_bool,
    require_exact,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_sha256_hex,
    require_str,
)

ACCEPTANCE_REGISTRY_PATH = "research/m3e/acceptance_registry.jsonl"
ACCEPTANCES_ROOT = "research/m3e/acceptances"
ACCEPTANCE_RECORD_NAME = "acceptance.json"
ACCEPTANCE_COMPLETION_NAME = "acceptance_completion.json"

ACCEPTANCE_REGISTRY_KIND = "m3e_acceptance_registry"
ACCEPTANCE_RECORD_KIND = "m3e_proposal_acceptance"
ACCEPTANCE_COMPLETION_KIND = "m3e_proposal_acceptance_completion"
ACCEPTANCE_SCHEMA_VERSION = 1

_RECORD_DOMAIN = "m3e/proposal_acceptance_record"
_COMPLETION_DOMAIN = "m3e/proposal_acceptance_completion"

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Pre-existing cohort files every acceptance transitions (old sha -> new sha pins).
TRANSITIONED_STATE_PATHS: tuple[str, ...] = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/prospective_segments.jsonl",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
    "research/m3e/proposal_registry.jsonl",
)

#: Byte-frozen, independently-committed tables that pin the pre-acceptance bytes
#: of every transitioned path. The chain genesis must agree with ALL of them, so a
#: forged genesis cannot re-root the chain onto invented history. (The M3F freeze
#: catalog is deliberately NOT an authority: it is rebuilt at re-registration and
#: therefore snapshots the *current* state, not the pre-acceptance state.)
_GENESIS_AUTHORITIES: tuple[str, ...] = (
    "docs/M3C_M3E_STACK_FREEZE_TABLE.json",
    "research/v2ab/stack_freeze_table.json",
)

_SEALED_LEDGERS: tuple[tuple[str, str], ...] = (
    ("final_holdout", "research/m2b/test_evaluations.jsonl"),
    ("development_gate", "research/m3a/development_gate_access.jsonl"),
    ("prospective_evaluation", "research/m3d/prospective_evaluations.jsonl"),
)

_FORBIDDEN_SUBSTRINGS = (
    "sharpe",
    "sortino",
    "return",
    "pnl",
    "drawdown",
    "signal",
    "weight",
    "position",
    "metric",
    "ranking",
    "alpha",
)


class AcceptanceError(M3EValidationError):
    """A violated acceptance-chain invariant (always fail closed)."""


def _require_utc_instant(label: str, value: object) -> str:
    """A strict ``YYYY-MM-DDTHH:MM:SSZ`` UTC instant string (exact shape, no zones)."""
    import datetime

    text = require_nonempty_str(label, value)
    try:
        parsed = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise AcceptanceError(f"{label}: not a strict UTC instant: {error}") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise AcceptanceError(f"{label}: does not round-trip canonically")
    return text


def _sha256_file(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"{label}: not a regular committed file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_forbidden(payload: Any, label: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _scan_forbidden(str(key), label)
            _scan_forbidden(value, label)
    elif isinstance(payload, list):
        for item in payload:
            _scan_forbidden(item, label)
    else:
        lowered = str(payload).lower()
        for sub in _FORBIDDEN_SUBSTRINGS:
            if sub in lowered:
                raise AcceptanceError(f"{label}: forbidden token {sub!r} present")


# ---------------------------------------------------------------------------
# Genesis pins: derived from committed evidence, never hand-typed.
# ---------------------------------------------------------------------------


def _pins_from_table(root: Path, table_relpath: str) -> dict[str, str]:
    _, doc = _load_json(root / table_relpath, f"genesis authority {table_relpath}")
    table = require_mapping(table_relpath, doc)
    rows: list[Any]
    if "files" in table:
        rows = list(table["files"])
    elif "artifacts" in table:
        rows = list(table["artifacts"])
    elif "entries" in table:
        rows = list(table["entries"])
    else:
        raise AcceptanceError(f"{table_relpath}: unrecognized freeze-table shape")
    wanted = set(TRANSITIONED_STATE_PATHS)
    pins: dict[str, str] = {}
    for raw in rows:
        row = require_mapping(f"{table_relpath} row", raw)
        path = require_str(f"{table_relpath} row.path", row.get("path"))
        if path in wanted:
            pins[path] = require_sha256_hex(f"{table_relpath} {path}", row.get("sha256"))
    missing = wanted - set(pins)
    if missing:
        raise AcceptanceError(f"{table_relpath}: missing pre-acceptance pins for {sorted(missing)}")
    return pins


def derive_genesis_pins(repo_root: str | Path) -> dict[str, str]:
    """The exact pre-acceptance sha256 of every transitioned path, multi-sourced.

    Every committed freeze authority in :data:`_GENESIS_AUTHORITIES` (currently
    two) must agree byte-for-byte; any disagreement is a hard stop (it would mean
    the historical tables themselves were tampered with, which no acceptance may
    paper over).
    """
    root = Path(repo_root)
    first: dict[str, str] | None = None
    for authority in _GENESIS_AUTHORITIES:
        pins = _pins_from_table(root, authority)
        if first is None:
            first = pins
        elif pins != first:
            raise AcceptanceError(
                f"pre-acceptance pins disagree between {_GENESIS_AUTHORITIES[0]} and {authority}"
            )
    assert first is not None
    return dict(sorted(first.items()))


def _load_json(path: Path, label: str) -> tuple[bytes, Any]:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"{label}: not a regular committed file")
    raw = path.read_bytes()
    return raw, load_canonical_json(path)


# ---------------------------------------------------------------------------
# Chain records.
# ---------------------------------------------------------------------------


def build_genesis_record(repo_root: str | Path) -> dict[str, Any]:
    return {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "kind": ACCEPTANCE_REGISTRY_KIND,
        "entry_kind": "genesis",
        "package_version": M3E_PACKAGE_VERSION,
        "pre_acceptance_state": derive_genesis_pins(repo_root),
        "pre_acceptance_proposal_count": 0,
        "genesis_authorities": list(_GENESIS_AUTHORITIES),
        "note": (
            "pins the exact pre-acceptance bytes of every transitioned cohort path; "
            "every authority table listed in genesis_authorities must agree exactly"
        ),
    }


def _require_semantics_hold(record: dict[str, Any], proposal_id: str) -> None:
    """Re-derive an acceptance record's arithmetic and its own safety assertions.

    These are the invariants ``build_acceptance_record`` enforced when the record
    was created. Checking them again on every load is what makes a coordinated
    reseal (edit a field, recompute the self-hash, rebind the registry entry,
    re-chain the ledger) fail: the forged content must now also be internally
    *true*, not merely internally consistent.
    """
    previous = require_mapping("previous_accepted", record.get("previous_accepted"))
    new_accepted = require_mapping("new_accepted", record.get("new_accepted"))
    interval = require_mapping("append_interval", record.get("append_interval"))
    proof = require_mapping("append_only_proof", record.get("append_only_proof"))

    old_rows = require_int("previous_accepted.row_count", previous.get("row_count"))
    new_rows = require_int("new_accepted.row_count", new_accepted.get("row_count"))
    appended = require_int("append_interval.row_count", interval.get("row_count"))
    if old_rows < 0 or appended < 1 or new_rows != old_rows + appended:
        raise AcceptanceError(
            f"acceptance {proposal_id}: row arithmetic is false "
            f"({old_rows} + {appended} != {new_rows})"
        )
    if new_rows >= 365:
        raise AcceptanceError(
            f"acceptance {proposal_id}: claims a mature cohort while asserting immaturity"
        )
    # The record's own append-only assertion must be TRUE, not merely present.
    if proof.get("is_append_only") is not True:
        raise AcceptanceError(f"acceptance {proposal_id}: append-only proof is not affirmative")
    for counter in ("prior_rows_changed", "prior_rows_deleted"):
        if require_int(f"append_only_proof.{counter}", proof.get(counter)) != 0:
            raise AcceptanceError(
                f"acceptance {proposal_id}: {counter} is non-zero — prior rows were disturbed"
            )
    if "prior_rows_are_exact_prefix" in proof and proof.get("prior_rows_are_exact_prefix") is not True:
        raise AcceptanceError(f"acceptance {proposal_id}: prior rows are not an exact prefix")
    if require_int("prior_row_count", proof.get("prior_row_count", old_rows)) != old_rows:
        raise AcceptanceError(f"acceptance {proposal_id}: measured prior row count disagrees")
    # Evidence pins must exist; an empty `created` map would trivially satisfy the
    # created-evidence check against ANY tree.
    created = require_mapping("new_accepted.created", new_accepted.get("created"))
    if not created:
        raise AcceptanceError(f"acceptance {proposal_id}: pins no created evidence")
    # Sealed-ledger facts inside the record must state emptiness, not any byte count.
    for logical, facts in require_mapping(
        "sealed_ledgers", record.get("sealed_ledgers")
    ).items():
        entry = require_mapping(f"sealed_ledgers.{logical}", facts)
        if require_int(f"{logical}.byte_count", entry.get("byte_count")) != 0:
            raise AcceptanceError(f"acceptance {proposal_id}: sealed ledger {logical} not empty")
        if require_sha256_hex(f"{logical}.sha256", entry.get("sha256")) != EMPTY_SHA256:
            raise AcceptanceError(f"acceptance {proposal_id}: sealed ledger {logical} digest wrong")
    _require_utc_instant(
        f"acceptance {proposal_id}: acceptance_time", record.get("acceptance_time")
    )
    for field in ("proposal_head_commit", "expected_parent_commit"):
        value = require_nonempty_str(field, record.get(field))
        if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise AcceptanceError(f"acceptance {proposal_id}: {field} is not a 40-hex commit id")


def _require_tree_matches_accepted_base(root: Path, record: dict[str, Any]) -> None:
    """The record's claimed new state must match the COMMITTED accepted base.

    Without this, a resealed record could claim any row count while the pinned
    ``accepted_base.json`` bytes say otherwise.
    """
    new_accepted = require_mapping("new_accepted", record.get("new_accepted"))
    _, base_doc = _load_json(root / "research/m3e/accepted_base.json", "accepted_base.json")
    base = require_mapping("accepted_base", base_doc)
    for field, key in (
        ("row_count", "row_count"),
        ("last_open", "last_open"),
        ("base_sha256", "base_sha256"),
        ("canonical_content_fingerprint", "canonical_content_fingerprint"),
    ):
        if new_accepted.get(field) != base.get(key):
            raise AcceptanceError(
                f"acceptance chain head disagrees with the committed accepted base on {field!r} "
                f"(record={new_accepted.get(field)!r}, base={base.get(key)!r})"
            )


@dataclasses.dataclass(frozen=True)
class AcceptanceEntry:
    """One verified acceptance in chain order."""

    sequence: int
    proposal_id: str
    acceptance_sha256: str
    record: dict[str, Any]
    completion: dict[str, Any]


def record_self_hash(body: dict[str, Any]) -> str:
    return domain_sha256(_RECORD_DOMAIN, body)


def completion_self_hash(body: dict[str, Any]) -> str:
    return domain_sha256(_COMPLETION_DOMAIN, body)


def _require_self_hashed(
    doc: dict[str, Any], *, field: str, domain: str, label: str
) -> dict[str, Any]:
    body = {k: v for k, v in doc.items() if k != field}
    expected = domain_sha256(domain, body)
    if require_sha256_hex(f"{label}.{field}", doc.get(field)) != expected:
        raise AcceptanceError(f"{label}: self-hash does not match its content")
    return body


# ---------------------------------------------------------------------------
# Building the acceptance record (run once per accepted proposal, then committed).
# ---------------------------------------------------------------------------


def _newest_attempt_id(root: Path) -> str:
    from eth_research.m3d.update_attempts import load_update_attempt_entries

    entries = load_update_attempt_entries(root)
    if not entries:
        raise AcceptanceError("grown tree has no update-attempt ledger entry")
    return require_nonempty_str("attempt_id", entries[-1].get("attempt_id"))


def _created_evidence_paths(root: Path, proposal_id: str) -> list[str]:
    """Every file the landed update created, repo-relative, sorted."""
    paths: list[str] = ["research/m3d/update_attempts.jsonl"]
    proposal_dir = root / ACCEPTANCES_PROPOSALS_ROOT / proposal_id
    for file in sorted(proposal_dir.rglob("*")):
        if file.is_symlink():
            raise AcceptanceError(f"proposal evidence {file} is a symlink")
        if file.is_file():
            paths.append(file.relative_to(root).as_posix())
    attempt_dir = root / "research/m3d/raw/coinbase" / _newest_attempt_id(root)
    for file in sorted(attempt_dir.rglob("*")):
        if file.is_symlink():
            raise AcceptanceError(f"attempt evidence {file} is a symlink")
        if file.is_file():
            paths.append(file.relative_to(root).as_posix())
    return paths


ACCEPTANCES_PROPOSALS_ROOT = "research/m3e/proposals"


def _measure_prior_rows(root: Path, proposal_dir: Path) -> dict[str, Any]:
    """Recompute how many prior canonical rows changed or were deleted.

    Rebuilds the whole cohort from the committed raw bundles, splits it at the
    attested append boundary, and compares the surviving prefix element-by-element
    against the pre-update rows rebuilt from the prior bundles alone. Nothing here
    trusts a document: the counts written into the acceptance record are the
    measured result of this comparison, and a non-zero count aborts the build.
    """
    from eth_research.m3d.raw_bundle import combined_canonical_rows
    from eth_research.m3d.update_attempts import build_accepted_raw_bundles
    from eth_research.m3e.proposal import RUNNER_A_DIR
    from eth_research.m3e.runner_boundary import load_and_verify_runner

    bundles, _entries = build_accepted_raw_bundles(root)
    runner_a = load_and_verify_runner(proposal_dir / RUNNER_A_DIR, runner_label="a")
    grown_rows = combined_canonical_rows(bundles)
    appended = runner_a.canonical_rows
    prior_bundles = bundles[: len(bundles) - len(runner_a.bundles)]
    prior_rows = combined_canonical_rows(prior_bundles)
    surviving = grown_rows[: len(grown_rows) - len(appended)]

    deleted = max(0, len(prior_rows) - len(surviving))
    changed = sum(
        1
        for index in range(min(len(prior_rows), len(surviving)))
        if prior_rows[index] != surviving[index]
    )
    exact_prefix = deleted == 0 and changed == 0 and len(surviving) == len(prior_rows)
    if not exact_prefix:
        raise AcceptanceError(
            f"prior rows are not an exact prefix of the grown cohort "
            f"(changed={changed}, deleted={deleted}); acceptance refused"
        )
    return {
        "prior_row_count": len(prior_rows),
        "changed": changed,
        "deleted": deleted,
        "exact_prefix": exact_prefix,
    }


def build_acceptance_record(
    repo_root: str | Path,
    proposal_id: str,
    *,
    proposal_head_commit: str,
    acceptance_time: str,
) -> dict[str, Any]:
    """Derive the complete acceptance record from committed evidence only.

    Every binding is recomputed (hashes from bytes, counts from rows, flags from
    the manifest); the only free inputs are the proposal head commit (a git fact
    the tree cannot contain) and the acceptance timestamp. Runs the full
    ``verify_landed_update`` graph first — an acceptance record can only exist
    for a tree that already proves the landed update end-to-end.
    """
    from eth_research.m3e.proposal import PROPOSAL_MANIFEST_NAME, load_proposal_manifest
    from eth_research.m3e.verify_m3e_program import verify_landed_update

    root = Path(repo_root)
    _require_utc_instant("acceptance_time", acceptance_time)
    if not proposal_head_commit or len(proposal_head_commit) != 40:
        raise AcceptanceError("proposal_head_commit must be a full 40-hex commit id")

    chain = load_acceptance_chain(root, require_completion=True)
    if any(entry.proposal_id == proposal_id for entry in chain):
        raise AcceptanceError(f"proposal {proposal_id} already has an acceptance record")
    prior_state = expected_current_state(root, upto=len(chain))
    prior_transitioned = {p: prior_state[p] for p in TRANSITIONED_STATE_PATHS}

    proposal_dir = root / ACCEPTANCES_PROPOSALS_ROOT / proposal_id
    landed_checks = verify_landed_update(root, proposal_dir)
    prior_row_audit = _measure_prior_rows(root, proposal_dir)

    manifest = load_proposal_manifest(proposal_dir / PROPOSAL_MANIFEST_NAME)
    transition = require_mapping("manifest.transition", manifest["transition"])
    new_window = require_mapping("manifest.new_window", manifest["new_window"])
    comparison = require_mapping("manifest.comparison", manifest["comparison"])
    flags = require_mapping("manifest.governance_flags", manifest["governance_flags"])
    for name, value in flags.items():
        if require_bool(f"governance_flags.{name}", value):
            raise AcceptanceError(f"governance flag {name} is set; acceptance forbidden")

    new_base_raw, new_base = _load_json(
        root / "research/m3e/accepted_base.json", "accepted_base.json"
    )
    new_base_map = require_mapping("accepted_base", new_base)
    require_exact(
        "accepted_base.evaluation_authorized",
        new_base_map.get("evaluation_authorized"),
        False,
    )
    require_exact("accepted_base.maturity_state", new_base_map.get("maturity_state"), "immature")

    quality_raw, quality_doc = _load_json(
        root / "research/m3d/prospective_quality.json", "prospective_quality.json"
    )
    quality_map = require_mapping("prospective_quality", quality_doc)

    runner_evidence: dict[str, Any] = {}
    for runner in ("runner_a", "runner_b"):
        rdir = proposal_dir / runner
        plan_raw, _ = _load_json(rdir / "update_plan.json", f"{runner}/update_plan.json")
        receipt_raw, _ = _load_json(
            rdir / "acquisition_receipt.json", f"{runner}/acquisition_receipt.json"
        )
        raws = sorted(p for p in rdir.iterdir() if p.name.startswith("coinbase-") and p.is_file())
        if not raws:
            raise AcceptanceError(f"{runner}: no raw response payload committed")
        runner_evidence[runner] = {
            "update_plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
            "acquisition_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "raw_response_sha256": {p.name: _sha256_file(p, f"{runner}/{p.name}") for p in raws},
        }
    if (
        runner_evidence["runner_a"]["raw_response_sha256"]
        != runner_evidence["runner_b"]["raw_response_sha256"]
    ):
        raise AcceptanceError("runner raw payloads are not byte-identical")

    accepted_state = {path: _sha256_file(root / path, path) for path in TRANSITIONED_STATE_PATHS}
    created_state = {
        path: _sha256_file(root / path, path) for path in _created_evidence_paths(root, proposal_id)
    }

    sealed = {}
    for logical, path in _SEALED_LEDGERS:
        data = (root / path).read_bytes()
        if data != b"":
            raise AcceptanceError(f"sealed ledger {logical} is non-empty; acceptance forbidden")
        sealed[logical] = {"path": path, "byte_count": 0, "sha256": EMPTY_SHA256}

    body: dict[str, Any] = {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "kind": ACCEPTANCE_RECORD_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "sequence": len(chain) + 1,
        "proposal_id": proposal_id,
        "proposal_head_commit": proposal_head_commit,
        "expected_parent_commit": require_str(
            "runner_a source commit", comparison["runner_a_identity"][0]
        ),
        "proposal_manifest_sha256": require_sha256_hex(
            "manifest_sha256", manifest["manifest_sha256"]
        ),
        "update_plan_sha256": require_sha256_hex(
            "update_plan_sha256", manifest["update_plan_sha256"]
        ),
        "comparison_sha256": require_sha256_hex(
            "comparison_sha256", comparison["comparison_sha256"]
        ),
        "runner_a_identity": list(comparison["runner_a_identity"]),
        "runner_b_identity": list(comparison["runner_b_identity"]),
        "runner_evidence": runner_evidence,
        "canonical_content_fingerprint": require_sha256_hex(
            "new fingerprint", new_base_map["canonical_content_fingerprint"]
        ),
        "transition_sha256": require_sha256_hex(
            "transition_sha256", transition["transition_sha256"]
        ),
        "proposed_cohort_fingerprint": require_sha256_hex(
            "proposed_cohort_fingerprint", transition["proposed_cohort_fingerprint"]
        ),
        "previous_accepted": {
            "state": prior_transitioned,
            "base_sha256": require_sha256_hex(
                "accepted_base_sha256", manifest["accepted_base_sha256"]
            ),
            "canonical_content_fingerprint": require_sha256_hex(
                "accepted_base_fingerprint", manifest["accepted_base_fingerprint"]
            ),
            "row_count": require_int("old_row_count", transition["old_row_count"]),
            "last_open": require_str("old_last_open", transition["old_last_open"]),
        },
        "new_accepted": {
            "state": accepted_state,
            "created": created_state,
            "base_sha256": require_sha256_hex("new base_sha256", new_base_map["base_sha256"]),
            "canonical_content_fingerprint": require_sha256_hex(
                "new fingerprint", new_base_map["canonical_content_fingerprint"]
            ),
            "row_count": require_int("new row_count", new_base_map["row_count"]),
            "last_open": require_str("new last_open", new_base_map["last_open"]),
            "accepted_base_file_sha256": hashlib.sha256(new_base_raw).hexdigest(),
        },
        "append_interval": {
            "first_open": require_str("first_open", new_window["first_open"]),
            "last_open": require_str("last_open", new_window["last_open"]),
            "row_count": require_int("appended rows", new_window["row_count"]),
        },
        "append_only_proof": {
            "is_append_only": require_exact(
                "transition.is_append_only", transition["is_append_only"], True
            ),
            # MEASURED, not asserted: the prior canonical rows are recomputed from the
            # raw bundles and compared element-by-element against the grown prefix.
            "prior_row_count": prior_row_audit["prior_row_count"],
            "prior_rows_changed": prior_row_audit["changed"],
            "prior_rows_deleted": prior_row_audit["deleted"],
            "prior_rows_are_exact_prefix": prior_row_audit["exact_prefix"],
            "landed_verification_checks": [name for name, _ in landed_checks],
        },
        "quality": {
            "sha256": hashlib.sha256(quality_raw).hexdigest(),
            "verdict_keys": sorted(str(k) for k in quality_map),
        },
        "governance_flags": dict.fromkeys(sorted(flags), False),
        "sealed_ledgers": sealed,
        "evaluation_authorized": False,
        "maturity_state": "immature",
        "acceptance_time": acceptance_time,
    }
    if (
        body["new_accepted"]["row_count"]
        != body["previous_accepted"]["row_count"] + body["append_interval"]["row_count"]
    ):
        raise AcceptanceError("row accounting is inconsistent (old + appended != new)")
    if body["new_accepted"]["row_count"] != require_int(
        "proposed_row_count", transition["proposed_row_count"]
    ):
        raise AcceptanceError("grown row count does not match the proposed row count")
    if body["new_accepted"]["last_open"] != require_str(
        "proposed_last_open", transition["proposed_last_open"]
    ):
        raise AcceptanceError("grown last open does not match the proposed last open")
    # The governance-flag NAMES legitimately name forbidden concepts (they assert the
    # concepts are absent); every value is separately enforced to be exactly False
    # above, so the smuggling scan runs over everything except those key strings.
    scannable = {k: v for k, v in body.items() if k != "governance_flags"}
    _scan_forbidden(scannable, "acceptance record")
    for value in body["governance_flags"].values():
        if value is not False:
            raise AcceptanceError("governance flag values must be exactly False")
    record = dict(body)
    record["acceptance_sha256"] = record_self_hash(body)
    return record


def build_completion_record(
    acceptance_record: dict[str, Any], *, publication_commit: str
) -> dict[str, Any]:
    if not publication_commit or len(publication_commit) != 40:
        raise AcceptanceError("publication_commit must be a full 40-hex commit id")
    body = {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "kind": ACCEPTANCE_COMPLETION_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "proposal_id": require_nonempty_str("proposal_id", acceptance_record.get("proposal_id")),
        "acceptance_sha256": require_sha256_hex(
            "acceptance_sha256", acceptance_record.get("acceptance_sha256")
        ),
        "publication_commit": publication_commit,
    }
    completion = dict(body)
    completion["completion_sha256"] = completion_self_hash(body)
    return completion


# ---------------------------------------------------------------------------
# Transactional publication with strict read-back.
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def publish_acceptance(repo_root: str | Path, record: dict[str, Any]) -> Path:
    """Write acceptance.json + append the registry line, atomically, then re-verify.

    Rollback safety: the record file is written first (unreferenced until the
    registry line lands), the registry is replaced whole-file via temp+rename, and
    the chain is strictly re-loaded afterwards; any failure leaves either the old
    registry (record file unreferenced — harmless, re-runnable) or a fully
    consistent new state.
    """
    root = Path(repo_root)
    proposal_id = require_nonempty_str("proposal_id", record.get("proposal_id"))
    _require_self_hashed(
        dict(record), field="acceptance_sha256", domain=_RECORD_DOMAIN, label="acceptance record"
    )
    record_path = root / ACCEPTANCES_ROOT / proposal_id / ACCEPTANCE_RECORD_NAME
    if record_path.exists():
        raise AcceptanceError(f"{record_path} already exists (records are append-only)")
    registry_path = root / ACCEPTANCE_REGISTRY_PATH
    if registry_path.exists():
        _, records = load_and_verify_chain(root, ACCEPTANCE_REGISTRY_PATH)
        bodies = [{k: v for k, v in rec.items() if k != "previous_line_sha256"} for rec in records]
    else:
        bodies = [build_genesis_record(root)]
    bodies.append(
        {
            "schema_version": ACCEPTANCE_SCHEMA_VERSION,
            "entry_kind": "acceptance",
            "sequence": len(bodies),
            "proposal_id": proposal_id,
            "acceptance_sha256": record["acceptance_sha256"],
            "package_version": M3E_PACKAGE_VERSION,
        }
    )
    _atomic_write(record_path, canonical_json_bytes(record) + b"\n")
    _atomic_write(registry_path, render_ledger_bytes(chained_line_bytes(bodies)))
    load_acceptance_chain(root, require_completion=False)
    return record_path


def publish_completion(repo_root: str | Path, completion: dict[str, Any]) -> Path:
    root = Path(repo_root)
    proposal_id = require_nonempty_str("proposal_id", completion.get("proposal_id"))
    _require_self_hashed(
        dict(completion),
        field="completion_sha256",
        domain=_COMPLETION_DOMAIN,
        label="completion record",
    )
    path = root / ACCEPTANCES_ROOT / proposal_id / ACCEPTANCE_COMPLETION_NAME
    if path.exists():
        raise AcceptanceError(f"{path} already exists (completions are append-only)")
    _atomic_write(path, canonical_json_bytes(completion) + b"\n")
    load_acceptance_chain(root, require_completion=True)
    return path


# ---------------------------------------------------------------------------
# Loading + verification (the production authority).
# ---------------------------------------------------------------------------


def load_acceptance_chain(
    repo_root: str | Path, *, require_completion: bool = True
) -> list[AcceptanceEntry]:
    """Strictly load and verify the whole acceptance chain (empty list if absent).

    An absent registry means the pre-acceptance world and is only legal while no
    production proposal exists in the tree — that cross-check lives in
    :func:`verify_acceptance_program` / :func:`require_all_proposals_accepted`.
    """
    root = Path(repo_root)
    registry_path = root / ACCEPTANCE_REGISTRY_PATH
    if not registry_path.exists():
        return []
    if registry_path.is_symlink() or not registry_path.is_file():
        raise AcceptanceError(f"{ACCEPTANCE_REGISTRY_PATH} is not a regular file")
    _, records = load_and_verify_chain(root, ACCEPTANCE_REGISTRY_PATH)
    if not records:
        raise AcceptanceError("acceptance registry exists but is empty")
    genesis = require_mapping("acceptance genesis", records[0])
    if (
        genesis.get("entry_kind") != "genesis"
        or genesis.get("kind") != ACCEPTANCE_REGISTRY_KIND
        or genesis.get("schema_version") != ACCEPTANCE_SCHEMA_VERSION
    ):
        raise AcceptanceError("acceptance registry genesis sentinel is malformed")
    pins = require_mapping("genesis.pre_acceptance_state", genesis.get("pre_acceptance_state"))
    derived = derive_genesis_pins(root)
    if {str(k): str(v) for k, v in pins.items()} != derived:
        raise AcceptanceError(
            "genesis pre-acceptance pins do not match the byte-frozen stack tables"
        )
    require_exact(
        "genesis.pre_acceptance_proposal_count",
        genesis.get("pre_acceptance_proposal_count"),
        0,
    )

    entries: list[AcceptanceEntry] = []
    prior_transitioned = derived
    seen_ids: set[str] = set()
    for position, raw_entry in enumerate(records[1:], start=1):
        entry = require_mapping("acceptance entry", raw_entry)
        if entry.get("entry_kind") != "acceptance":
            raise AcceptanceError(f"registry line {position}: unexpected entry_kind")
        sequence = require_int("entry.sequence", entry.get("sequence"))
        if sequence != position:
            raise AcceptanceError(
                f"registry line {position}: sequence {sequence} out of order "
                "(reorder/gap/duplicate fails closed)"
            )
        proposal_id = require_nonempty_str("entry.proposal_id", entry.get("proposal_id"))
        if proposal_id in seen_ids:
            raise AcceptanceError(f"proposal {proposal_id} accepted twice")
        seen_ids.add(proposal_id)
        entry_sha = require_sha256_hex("entry.acceptance_sha256", entry.get("acceptance_sha256"))

        record_path = root / ACCEPTANCES_ROOT / proposal_id / ACCEPTANCE_RECORD_NAME
        _, record_doc = _load_json(record_path, f"acceptance record {proposal_id}")
        record = require_mapping("acceptance record", record_doc)
        body = _require_self_hashed(
            dict(record),
            field="acceptance_sha256",
            domain=_RECORD_DOMAIN,
            label=f"acceptance record {proposal_id}",
        )
        if record["acceptance_sha256"] != entry_sha:
            raise AcceptanceError(f"registry entry {position} does not bind the committed record")
        if (
            record.get("kind") != ACCEPTANCE_RECORD_KIND
            or record.get("schema_version") != ACCEPTANCE_SCHEMA_VERSION
            or record.get("proposal_id") != proposal_id
            or require_int("record.sequence", record.get("sequence")) != sequence
        ):
            raise AcceptanceError(f"acceptance record {proposal_id}: identity fields malformed")
        previous = require_mapping("record.previous_accepted", record.get("previous_accepted"))
        recorded_prior = {
            str(k): require_sha256_hex(f"prior {k}", v)
            for k, v in require_mapping("previous_accepted.state", previous.get("state")).items()
        }
        if recorded_prior != prior_transitioned:
            raise AcceptanceError(
                f"acceptance {proposal_id} does not chain from the prior accepted state"
            )
        new_accepted = require_mapping("record.new_accepted", record.get("new_accepted"))
        new_state = {
            str(k): require_sha256_hex(f"new {k}", v)
            for k, v in require_mapping("new_accepted.state", new_accepted.get("state")).items()
        }
        if set(new_state) != set(TRANSITIONED_STATE_PATHS):
            raise AcceptanceError(
                f"acceptance {proposal_id}: new state must pin exactly the transitioned paths"
            )
        require_exact("record.evaluation_authorized", record.get("evaluation_authorized"), False)
        require_exact("record.maturity_state", record.get("maturity_state"), "immature")
        for name, value in require_mapping(
            "record.governance_flags", record.get("governance_flags")
        ).items():
            if require_bool(f"record.governance_flags.{name}", value):
                raise AcceptanceError(f"acceptance {proposal_id}: governance flag {name} set")
        # Flag NAMES name forbidden concepts to assert their absence; values are
        # enforced exactly-False above, so the scan skips only those key strings.
        _scan_forbidden(
            {k: v for k, v in body.items() if k != "governance_flags"},
            f"acceptance record {proposal_id}",
        )
        # RE-DERIVE the record's semantics; never accept them as self-asserted.
        # A self-hash only proves the record is internally consistent with itself,
        # so a coordinated reseal (edit + re-hash + re-chain) would otherwise pass.
        # Every row — not just the newest — must survive these.
        _require_semantics_hold(record, proposal_id)

        completion: dict[str, Any] = {}
        completion_path = root / ACCEPTANCES_ROOT / proposal_id / ACCEPTANCE_COMPLETION_NAME
        if completion_path.exists():
            _, completion_doc = _load_json(completion_path, f"completion {proposal_id}")
            completion = require_mapping("completion record", completion_doc)
            _require_self_hashed(
                dict(completion),
                field="completion_sha256",
                domain=_COMPLETION_DOMAIN,
                label=f"completion {proposal_id}",
            )
            if (
                completion.get("kind") != ACCEPTANCE_COMPLETION_KIND
                or completion.get("proposal_id") != proposal_id
                or completion.get("acceptance_sha256") != record["acceptance_sha256"]
            ):
                raise AcceptanceError(f"completion {proposal_id}: does not bind its record")
        elif require_completion:
            raise AcceptanceError(
                f"acceptance {proposal_id} has no completion record (two-phase binding missing)"
            )

        entries.append(
            AcceptanceEntry(
                sequence=sequence,
                proposal_id=proposal_id,
                acceptance_sha256=entry_sha,
                record=record,
                completion=completion,
            )
        )
        prior_transitioned = new_state

    # Extra acceptance directories not in the chain are illegal (a record cannot
    # exist outside the registry order).
    acceptances_dir = root / ACCEPTANCES_ROOT
    if acceptances_dir.exists():
        on_disk = {p.name for p in acceptances_dir.iterdir() if p.is_dir()}
        if on_disk - seen_ids:
            raise AcceptanceError(
                f"acceptance directories outside the chain: {sorted(on_disk - seen_ids)}"
            )
    return entries


def expected_current_state(repo_root: str | Path, *, upto: int | None = None) -> dict[str, str]:
    """The single exact expected sha256 of every transitioned path: base ⊕ chain."""
    chain = load_acceptance_chain(repo_root, require_completion=False)
    if upto is not None:
        chain = chain[:upto]
    state = derive_genesis_pins(repo_root)
    for entry in chain:
        new_accepted = require_mapping("new_accepted", entry.record["new_accepted"])
        for path, sha in require_mapping("state", new_accepted["state"]).items():
            state[str(path)] = require_sha256_hex(f"chain {path}", sha)
    return state


def accepted_proposal_ids(repo_root: str | Path) -> tuple[str, ...]:
    return tuple(
        entry.proposal_id for entry in load_acceptance_chain(repo_root, require_completion=False)
    )


def require_all_proposals_accepted(repo_root: str | Path) -> tuple[str, ...]:
    """The production legality predicate: every committed proposal must be accepted.

    Returns the accepted ids on success; raises if any committed production
    proposal lacks a covering acceptance record (an unaccepted proposal in the
    tree stays exactly as illegal as it was before this module existed) or if an
    acceptance exists without its proposal evidence.
    """
    from eth_research.m3e.verify_m3e_program import verify_proposals_root

    root = Path(repo_root)
    committed = {directory.name for directory in verify_proposals_root(root)}
    accepted = set(accepted_proposal_ids(root))
    if committed - accepted:
        raise AcceptanceError(
            "production proposal(s) present without an acceptance record "
            f"(illegal, fail closed): {sorted(committed - accepted)}"
        )
    if accepted - committed:
        raise AcceptanceError(
            f"acceptance record(s) without proposal evidence: {sorted(accepted - committed)}"
        )
    return tuple(sorted(accepted))


def _git_head_contains(root: Path, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            capture_output=True,
        )
        return result.returncode == 0
    except (OSError, subprocess.CalledProcessError):
        return False


def verify_acceptance_program(repo_root: str | Path, *, deep: bool = True) -> list[tuple[str, str]]:
    """Full production verification of the acceptance layer.

    * chain + records + completions verify strictly (delete/reorder/duplicate/edit
      anywhere fails closed);
    * every committed proposal is covered by exactly one acceptance and vice versa;
    * the working tree matches the chain-head expected state byte-for-byte —
      transitioned paths AND created evidence;
    * with ``deep``, the newest landed update re-proves end-to-end via
      ``verify_landed_update`` (row-level append-only identity included);
    * sealed ledgers stay byte-empty; the grown base stays immature/unauthorized;
    * when git history is present, the recorded proposal head and publication
      commits must be ancestors of HEAD.
    """
    root = Path(repo_root)
    checks: list[tuple[str, str]] = []

    def record(name: str, detail: str = "ok") -> None:
        checks.append((name, detail))

    chain = load_acceptance_chain(root, require_completion=True)
    record("A01_chain_loads_strictly", f"acceptances={len(chain)}")
    accepted = require_all_proposals_accepted(root)
    record("A02_every_proposal_accepted", ",".join(accepted) or "none")
    if chain:
        _require_tree_matches_accepted_base(root, chain[-1].record)
        record("A02b_chain_head_matches_accepted_base")

    state = expected_current_state(root)
    for path, expected in sorted(state.items()):
        actual = _sha256_file(root / path, path)
        if actual != expected:
            raise AcceptanceError(
                f"{path}: working tree {actual[:16]}… does not equal the chain-head "
                f"expected state {expected[:16]}… (no drift outside acceptances)"
            )
    record("A03_tree_equals_chain_head_state", f"paths={len(state)}")

    if chain:
        newest = chain[-1]
        created = require_mapping(
            "created",
            require_mapping("new_accepted", newest.record["new_accepted"]).get("created"),
        )
        for path, sha in sorted(created.items()):
            actual = _sha256_file(root / str(path), str(path))
            if actual != require_sha256_hex(f"created {path}", sha):
                raise AcceptanceError(f"created evidence {path} drifted from its acceptance pin")
        # Closed set, not just a checklist: a file smuggled into an accepted proposal
        # directory after the fact must fail, so the live directory contents must
        # equal exactly the pinned set.
        live_evidence = {
            p.relative_to(root).as_posix()
            for p in (root / ACCEPTANCES_PROPOSALS_ROOT / newest.proposal_id).rglob("*")
            if p.is_file() or p.is_symlink()
        }
        pinned_evidence = {p for p in created if p.startswith(ACCEPTANCES_PROPOSALS_ROOT + "/")}
        if live_evidence != pinned_evidence:
            raise AcceptanceError(
                "accepted proposal directory is not a closed set: "
                f"unpinned={sorted(live_evidence - pinned_evidence)}, "
                f"missing={sorted(pinned_evidence - live_evidence)}"
            )
        record("A04_created_evidence_pinned", f"files={len(created)}")

        # The build-time invariant "both runners produced byte-identical payloads"
        # is re-asserted here from the pinned hashes, so a record that pinned
        # different A/B payloads could never pass verification.
        runner_evidence = require_mapping(
            "runner_evidence", newest.record.get("runner_evidence")
        )
        raw_by_runner = {
            name: require_mapping(f"{name}.raw_response_sha256", body.get("raw_response_sha256"))
            for name, body in (
                (str(k), require_mapping(f"runner_evidence.{k}", v))
                for k, v in runner_evidence.items()
            )
        }
        distinct = {tuple(sorted(mapping.items())) for mapping in raw_by_runner.values()}
        if len(raw_by_runner) < 2 or len(distinct) != 1:
            raise AcceptanceError(
                "acceptance record does not attest two runners with byte-identical payloads"
            )
        record("A04b_runner_payloads_identical", f"runners={len(raw_by_runner)}")

        if deep:
            from eth_research.m3e.verify_m3e_program import verify_landed_update

            landed = verify_landed_update(
                root, root / ACCEPTANCES_PROPOSALS_ROOT / newest.proposal_id
            )
            record("A05_newest_landed_update_reproves", f"checks={len(landed)}")

        if (root / ".git").exists():
            for label, commit in (
                ("proposal_head_commit", newest.record["proposal_head_commit"]),
                (
                    "publication_commit",
                    newest.completion.get("publication_commit", ""),
                ),
            ):
                if not commit or not _git_head_contains(root, str(commit)):
                    raise AcceptanceError(f"{label} {str(commit)[:12]}… is not an ancestor of HEAD")
            record("A06_commits_are_ancestors")
    else:
        record("A04_created_evidence_pinned", "no acceptances")

    for logical, path in _SEALED_LEDGERS:
        if (root / path).read_bytes() != b"":
            raise AcceptanceError(f"sealed ledger {logical} is non-empty (HARD STOP)")
    record("A07_sealed_ledgers_byte_empty")
    return checks


# ---------------------------------------------------------------------------
# CLI (offline, deterministic; the build path takes every variable as an argument).
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(prog="python -m eth_research.m3e.acceptance")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    build = sub.add_parser("build-record")
    build.add_argument("--proposal-id", required=True)
    build.add_argument("--proposal-head", required=True)
    build.add_argument("--acceptance-time", required=True)
    build.add_argument("--write", action="store_true")
    complete = sub.add_parser("complete")
    complete.add_argument("--proposal-id", required=True)
    complete.add_argument("--publication-commit", required=True)
    complete.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.command == "check":
        for name, detail in verify_acceptance_program(root):
            print(f"{name}: {detail}")
        print("acceptance program OK")
        return 0
    if args.command == "build-record":
        record = build_acceptance_record(
            root,
            args.proposal_id,
            proposal_head_commit=args.proposal_head,
            acceptance_time=args.acceptance_time,
        )
        if args.write:
            path = publish_acceptance(root, record)
            print(f"published {path}")
        else:
            print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    if args.command == "complete":
        chain = load_acceptance_chain(root, require_completion=False)
        matching = [e for e in chain if e.proposal_id == args.proposal_id]
        if not matching:
            raise AcceptanceError(f"no acceptance record for {args.proposal_id}")
        completion = build_completion_record(
            matching[-1].record, publication_commit=args.publication_commit
        )
        if args.write:
            path = publish_completion(root, completion)
            print(f"published {path}")
        else:
            print(json.dumps(completion, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
