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

import hashlib
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_mapping,
    require_str,
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
GROWABLE_NEW_FILES: tuple[str, ...] = ("research/m3d/update_attempts.jsonl",)
GROWABLE_NEW_PATH_PREFIXES: tuple[str, ...] = (
    "research/m3e/proposals/",
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
