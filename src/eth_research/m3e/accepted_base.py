"""The verified accepted prospective base — M3E's single trusted input.

Every update proposal M3E can ever make is anchored on the *accepted* M3D
prospective cohort. Before any planning, acquisition, comparison, transition, or
proposal, M3E re-derives that accepted state from committed M3D bytes and binds it
into an :class:`AcceptedProspectiveBase`:

* the cohort manifest rebuilds byte-for-byte and is ``immature`` /
  ``evaluation_authorized: false`` (via the reviewed M3D verifier);
* the segment chain rebuilds byte-for-byte;
* the canonical cohort content re-derives from the committed raw bytes and matches
  the manifest's fingerprint (``bb6dd392…``);
* the two sealed access ledgers and the prospective evaluation ledger are all
  byte-empty (SHA-256 ``e3b0c442…``);
* the M3C candidate is still recorded ``rejected_for_development_gate_promotion``.

The base is the **trust boundary**: everything downstream (network bytes, proposal
bytes) is untrusted and must be re-derived and compared against this anchor. The
committed ``research/m3e/accepted_base.json`` snapshot is a deterministic function
of committed M3D evidence, so :func:`verify_accepted_base` rebuilds it and requires
a byte-for-byte match — a drift on any accepted M3D byte fails here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.cohort import MANIFEST_PATH, verify_cohort_manifest
from eth_research.m3d.protocol import COHORT_START, MINIMUM_MATURITY_ROWS
from eth_research.m3d.publication import PUBLICATION_MANIFEST_PATH
from eth_research.m3d.raw_bundle import cohort_canonical_fingerprint
from eth_research.m3d.reacquisition_audit import REACQUISITION_AUDIT_PATH
from eth_research.m3d.segment import SEGMENTS_PATH, verify_prospective_segments
from eth_research.m3d.update_attempts import (
    UPDATE_ATTEMPTS_PATH,
    build_accepted_raw_bundles,
)
from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    domain_sha256,
    load_canonical_json_bytes,
    require_exact,
    require_mapping,
    require_nonnegative_int,
    require_str,
)

ACCEPTED_BASE_PATH = "research/m3e/accepted_base.json"
ACCEPTED_BASE_SCHEMA_VERSION = 1
ACCEPTED_BASE_KIND = "accepted_prospective_base"
ACCEPTED_BASE_DOMAIN = "m3e_accepted_prospective_base"
_INTERVAL_SECONDS = 86400
_PRODUCT = "ETH-USD"
_VENUE = "coinbase-exchange"

# The three ledgers that must stay byte-empty; their logical name → committed path.
_LEDGERS: dict[str, str] = {
    "development_gate": up.SEALED_LEDGERS["development_gate"],
    "final_holdout": up.SEALED_LEDGERS["final_holdout"],
    "prospective_evaluation": up.PROSPECTIVE_EVALUATION_LEDGER,
}


@dataclass(frozen=True)
class AcceptedProspectiveBase:
    """A verified, immutable view of the accepted M3D prospective cohort."""

    document: dict[str, Any]

    @property
    def last_open(self) -> str:
        return str(self.document["last_open"])

    @property
    def first_open(self) -> str:
        return str(self.document["first_open"])

    @property
    def row_count(self) -> int:
        return int(self.document["row_count"])

    @property
    def canonical_content_fingerprint(self) -> str:
        return str(self.document["canonical_content_fingerprint"])

    @property
    def base_sha256(self) -> str:
        return str(self.document["base_sha256"])

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)


def _empty_ledger_facts(repo_root: str | Path, name: str, path: str) -> dict[str, Any]:
    facts = up.ledger_facts(repo_root, path)
    if facts["byte_count"] != 0 or facts["sha256"] != up.EMPTY_SHA256:
        raise M3EValidationError(f"ledger {name} must be byte-empty (HARD STOP)")
    return {"path": path, "byte_count": 0, "sha256": up.EMPTY_SHA256}


def build_accepted_base_document(repo_root: str | Path) -> dict[str, Any]:
    """Re-derive the accepted base from committed M3D bytes (never live git).

    Rebuilds and verifies the M3D manifest and segment chain, re-derives the
    canonical fingerprint from the committed raw bytes and cross-checks it against
    the manifest, proves the three ledgers byte-empty, and proves the M3C candidate
    is still rejected. Raises on any drift.
    """
    root = Path(repo_root)

    # 1. Manifest rebuilds byte-for-byte and is immature / unauthorized.
    manifest = verify_cohort_manifest(root)
    # 2. Segment chain rebuilds byte-for-byte.
    verify_prospective_segments(root)
    # 3. Canonical content re-derives from raw bytes (genesis + every landed update
    #    attempt, cross-checked) and matches the manifest.
    bundles, update_entries = build_accepted_raw_bundles(root)
    fingerprint = cohort_canonical_fingerprint(bundles)
    manifest_fp = require_str(
        "manifest.canonical_content_fingerprint", manifest["canonical_content_fingerprint"]
    )
    if fingerprint != manifest_fp:
        raise M3EValidationError("re-derived cohort fingerprint does not match the manifest")

    first_open = require_str("first_open", manifest["first_open"])
    last_open = require_str("last_open", manifest["last_open"])
    row_count = require_nonnegative_int("row_count", manifest["row_count"])
    if require_str("cohort_start", manifest["cohort_start"]) != COHORT_START:
        raise M3EValidationError("accepted base cohort_start drifted from the fixed start")

    # 4. Three ledgers byte-empty.
    ledgers = {
        name: _empty_ledger_facts(root, name, path) for name, path in sorted(_LEDGERS.items())
    }

    # 5. M3C candidate still rejected.
    decision = up.load_json(root, up.ANCHORS["m3c"]["candidate_decision"])
    outcome = decision.get("outcome") if isinstance(decision, dict) else None
    if outcome != up.M3C_REJECTED_OUTCOME:
        raise M3EValidationError(f"M3C candidate outcome changed to {outcome!r} (HARD STOP)")

    provenance = {
        "manifest_sha256": up.hash_file(root, MANIFEST_PATH),
        "segment_chain_sha256": up.hash_file(root, SEGMENTS_PATH),
        "reacquisition_audit_sha256": up.hash_file(root, REACQUISITION_AUDIT_PATH),
        "publication_manifest_sha256": up.hash_file(root, PUBLICATION_MANIFEST_PATH),
        "m3c_candidate_decision_outcome": up.M3C_REJECTED_OUTCOME,
    }
    # V2D growth: bind the update-attempts ledger once at least one update landed;
    # a pre-growth base snapshot stays byte-for-byte identical without it.
    if update_entries:
        provenance["update_attempts_ledger_sha256"] = up.hash_file(root, UPDATE_ATTEMPTS_PATH)

    document: dict[str, Any] = {
        "schema_version": ACCEPTED_BASE_SCHEMA_VERSION,
        "kind": ACCEPTED_BASE_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "upstream_milestone": "M3D",
        "identity": {
            "product": _PRODUCT,
            "venue": _VENUE,
            "interval_seconds": _INTERVAL_SECONDS,
        },
        "cohort_start": COHORT_START,
        "first_open": first_open,
        "last_open": last_open,
        "row_count": row_count,
        "canonical_content_fingerprint": fingerprint,
        "minimum_maturity_rows": MINIMUM_MATURITY_ROWS,
        "maturity_state": require_exact(
            "maturity_state", str(manifest["maturity_state"]), "immature"
        ),
        "evaluation_authorized": require_exact(
            "evaluation_authorized", bool(manifest["evaluation_authorized"]), False
        ),
        "provenance": provenance,
        "ledgers": ledgers,
    }
    document["base_sha256"] = domain_sha256(ACCEPTED_BASE_DOMAIN, document)
    return document


def build_accepted_base_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the accepted-base snapshot bytes."""
    return canonical_json_bytes(build_accepted_base_document(repo_root))


def _from_mapping(doc: object) -> AcceptedProspectiveBase:
    mapping = require_mapping("accepted_prospective_base", doc)
    require_exact(
        "schema_version",
        require_nonnegative_int("schema_version", mapping.get("schema_version")),
        ACCEPTED_BASE_SCHEMA_VERSION,
    )
    require_exact("kind", require_str("kind", mapping.get("kind")), ACCEPTED_BASE_KIND)
    # Recompute the base hash over the document minus its own hash field.
    body = {k: v for k, v in mapping.items() if k != "base_sha256"}
    expected = domain_sha256(ACCEPTED_BASE_DOMAIN, body)
    if require_str("base_sha256", mapping.get("base_sha256")) != expected:
        raise M3EValidationError("accepted base base_sha256 does not match its content")
    return AcceptedProspectiveBase(document=dict(mapping))


def load_accepted_base(path: str | Path) -> AcceptedProspectiveBase:
    """Strictly load a committed accepted-base snapshot (canonical bytes required)."""
    _raw, doc = load_canonical_json_bytes(Path(path), "accepted_prospective_base")
    return _from_mapping(doc)


def verify_accepted_base(repo_root: str | Path) -> AcceptedProspectiveBase:
    """Verify the committed accepted-base snapshot reproduces from M3D evidence."""
    root = Path(repo_root)
    rebuilt = build_accepted_base_bytes(root)
    raw = (root / ACCEPTED_BASE_PATH).read_bytes()
    if raw != rebuilt:
        raise M3EValidationError("committed accepted_base.json does not match the rebuild")
    return _from_mapping(build_accepted_base_document(root))
