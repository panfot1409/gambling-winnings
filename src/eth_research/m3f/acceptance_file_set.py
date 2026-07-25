"""Independent re-derivation of an acceptance record's closed proposal file set.

The M3E acceptance record carries a ``file_set_binding``: the identity of the
legal file set for its proposal, derived by policy from the two pinned commits.
``eth_research.m3e`` verifies that binding with the same code that wrote it. This
module re-derives it a second time, from git, inside the isolated M3F verifier —
so a transcription bug, a wrong regex or a mis-ordered digest in one
implementation does not silently become the definition of "correct".

What this buys and what it does not
-----------------------------------
This is **implementation diversity**, not an external trust anchor. Both
implementations read the same repository and the same git objects; an actor who
can rewrite committed source and history can rewrite both. What diversity does
buy is that a defect confined to one implementation is caught, and that a
coordinated data-plane forgery must now satisfy two separately written
derivations of the same policy.

Deliberate non-reuse
--------------------
The path→role rules below are written from the policy specification, not
imported from ``eth_research.m3e`` — M3F's isolation guarantee allows only
``eth_research._json``, and reuse would defeat the point regardless. They must
therefore be kept in step with the policy by TEST, not by trust: see
``tests/test_m3f_acceptance_file_set.py``, which cross-checks every path in the
real proposal against the m3e classifier and fails on divergence.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    require_mapping,
    require_str,
)

#: Mirrors ``eth_research.m3e.proposal_file_policy.FILE_SET_POLICY_ID``.
EXPECTED_POLICY_ID: Final[str] = "m3e-proposal-file-policy-v1"
EXPECTED_BINDING_SCHEMA_VERSION: Final[int] = 1

_D_TREE: Final[str] = "m3e/proposal_file_policy/tree"
_D_NAME_STATUS: Final[str] = "m3e/proposal_file_policy/diff_name_status"
_D_NUMSTAT: Final[str] = "m3e/proposal_file_policy/diff_numstat"
_D_PATHS: Final[str] = "m3e/proposal_file_policy/path_set"
_D_BUNDLE: Final[str] = "m3e/proposal_file_policy/bundle"

_ALLOWED_ROOTS: Final[tuple[str, ...]] = ("research/m3d/", "research/m3e/")
_ALLOWED_SUFFIXES: Final[tuple[str, ...]] = (".json", ".jsonl")
_ALLOWED_MODE: Final[str] = "100644"

_M3D_RAW_PREFIX: Final[str] = "research/m3d/raw/coinbase/"
_M3E_PROPOSALS_PREFIX: Final[str] = "research/m3e/proposals/"
_UPDATE_ATTEMPTS_PATH: Final[str] = "research/m3d/update_attempts.jsonl"
_TRANSITIONED_STATE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "research/m3d/prospective_manifest.json",
        "research/m3d/prospective_quality.json",
        "research/m3d/prospective_segments.jsonl",
        "research/m3d/publication_manifest.json",
        "research/m3e/accepted_base.json",
        "research/m3e/proposal_registry.jsonl",
    }
)
_PROPOSAL_DOCUMENT_BASENAMES: Final[frozenset[str]] = frozenset(
    {"proposal_manifest.json", "acquisition_comparison.json", "update_transition.json"}
)
_RUNNER_DIRS: Final[frozenset[str]] = frozenset({"runner_a", "runner_b"})
_RAW_RESPONSE_RE: Final[re.Pattern[str]] = re.compile(
    r"^coinbase-eth-usd-1d-update_\d{4}_\d{8}_\d{8}\.json$"
)
_BUNDLE_DIR_TEMPLATE: Final[str] = r"^coinbase-eth-usd-prospective-update-\d{8}-\d{8}-%s$"
_PROPOSAL_ID_RE: Final[re.Pattern[str]] = re.compile(r"^\d{8}-\d{8}-[0-9a-f]{16}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_ASCII_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._/-]+$")

# Role names, mirroring the policy's ROLE_* constants.
_ROLE_TRANSITIONED_STATE: Final[str] = "transitioned_state"
_ROLE_UPDATE_ATTEMPTS: Final[str] = "update_attempts_ledger"
_ROLE_BUNDLE_PLAN: Final[str] = "m3d_bundle_plan"
_ROLE_BUNDLE_RECEIPT: Final[str] = "m3d_bundle_receipt"
_ROLE_BUNDLE_RAW: Final[str] = "m3d_bundle_raw_response"
_ROLE_PROPOSAL_DOC: Final[str] = "proposal_document"
_ROLE_RUNNER_PLAN: Final[str] = "runner_update_plan"
_ROLE_RUNNER_RECEIPT: Final[str] = "runner_acquisition_receipt"
_ROLE_RUNNER_RAW: Final[str] = "runner_raw_response"

_MANIFEST_ROLES: Final[frozenset[str]] = frozenset(
    {_ROLE_PROPOSAL_DOC, _ROLE_RUNNER_PLAN, _ROLE_RUNNER_RECEIPT, _ROLE_RUNNER_RAW}
)
_RAW_ROLES: Final[frozenset[str]] = frozenset({_ROLE_BUNDLE_RAW, _ROLE_RUNNER_RAW})
_GOVERNANCE_ROLES: Final[frozenset[str]] = frozenset(
    {_ROLE_TRANSITIONED_STATE, _ROLE_UPDATE_ATTEMPTS}
)

_MAX_GIT_BYTES: Final[int] = 8 * 1024 * 1024
_GIT_TIMEOUT: Final[int] = 120


def _domain_sha256(domain: str, payload: Any) -> str:
    """The M3E/M3D domain-separated digest, recomputed here from its definition.

    ``m3d/<domain>\\n`` length-tagged prefix over the same canonical JSON form
    M3F already implements; if the two canonicalizations ever diverge, every
    digest below diverges loudly rather than silently agreeing."""
    return hashlib.sha256(f"m3d/{domain}\n".encode() + canonical_json_bytes(payload)).hexdigest()


def _digest_paths(paths: list[str]) -> str:
    return _domain_sha256(_D_PATHS, {"paths": sorted(paths)})


def _git(repo_root: Path, argv: list[str]) -> bytes:
    """Read-only git, argv array only (never a shell string), bounded output."""
    proc = subprocess.run(  # fixed argv, never a shell string
        ["git", "-C", str(repo_root), *argv],
        capture_output=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise M3FValidationError(f"git {' '.join(argv)} failed: {detail}")
    if len(proc.stdout) > _MAX_GIT_BYTES:
        raise M3FValidationError(f"git {' '.join(argv)} produced more than {_MAX_GIT_BYTES} bytes")
    return proc.stdout


def _require_commit(label: str, value: object) -> str:
    text = require_str(value, label)
    if not _COMMIT_RE.fullmatch(text):
        raise M3FValidationError(f"{label} is not a full lowercase 40-hex commit id: {text!r}")
    return text


def _classify(path: str, proposal_id: str) -> str:
    """Path → policy role, from the path and the proposal identity and nothing else.

    Written independently of the m3e classifier on purpose. Anything this
    function cannot name is refused, so an unknown file can never be silently
    admitted as some default role."""
    if not path or not _ASCII_PATH_RE.fullmatch(path) or path != path.strip():
        raise M3FValidationError(f"unlawful path spelling: {path!r}")
    if path.startswith("/") or ".." in path.split("/") or "//" in path:
        raise M3FValidationError(f"unlawful path shape: {path!r}")
    if any(segment.startswith(".") for segment in path.split("/")):
        raise M3FValidationError(f"hidden/dotfile path: {path}")
    if not path.startswith(_ALLOWED_ROOTS):
        raise M3FValidationError(f"path outside the allowed roots: {path}")
    if not path.endswith(_ALLOWED_SUFFIXES):
        raise M3FValidationError(f"path has a disallowed extension: {path}")

    if path in _TRANSITIONED_STATE_PATHS:
        return _ROLE_TRANSITIONED_STATE
    if path == _UPDATE_ATTEMPTS_PATH:
        return _ROLE_UPDATE_ATTEMPTS

    if path.startswith(_M3D_RAW_PREFIX):
        tail = path[len(_M3D_RAW_PREFIX) :].split("/")
        if len(tail) != 2:
            raise M3FValidationError(f"unknown file under the m3d raw root: {path}")
        bundle, name = tail
        if not re.fullmatch(_BUNDLE_DIR_TEMPLATE % re.escape(proposal_id[-16:]), bundle):
            raise M3FValidationError(f"raw bundle does not belong to {proposal_id}: {path}")
        if name == "acquisition_plan.json":
            return _ROLE_BUNDLE_PLAN
        if name == "acquisition_receipt.json":
            return _ROLE_BUNDLE_RECEIPT
        if _RAW_RESPONSE_RE.fullmatch(name):
            return _ROLE_BUNDLE_RAW
        raise M3FValidationError(f"unknown file in the m3d raw bundle: {path}")

    if path.startswith(_M3E_PROPOSALS_PREFIX):
        tail = path[len(_M3E_PROPOSALS_PREFIX) :].split("/")
        if tail[0] != proposal_id:
            raise M3FValidationError(f"file belongs to another proposal than {proposal_id}: {path}")
        rest = tail[1:]
        if len(rest) == 1:
            if rest[0] in _PROPOSAL_DOCUMENT_BASENAMES:
                return _ROLE_PROPOSAL_DOC
            raise M3FValidationError(f"unknown file in the proposal directory: {path}")
        if len(rest) == 2:
            runner, name = rest
            if runner not in _RUNNER_DIRS:
                raise M3FValidationError(f"unknown runner directory: {path}")
            if name == "update_plan.json":
                return _ROLE_RUNNER_PLAN
            if name == "acquisition_receipt.json":
                return _ROLE_RUNNER_RECEIPT
            if _RAW_RESPONSE_RE.fullmatch(name):
                return _ROLE_RUNNER_RAW
            raise M3FValidationError(f"unknown file in a runner directory: {path}")
        raise M3FValidationError(f"proposal directory is nested too deeply: {path}")

    raise M3FValidationError(f"unknown file (no policy rule admits it): {path}")


def _ls_tree(repo_root: Path, commit: str) -> dict[str, tuple[str, str, str]]:
    """``{path: (mode, type, sha)}`` for the full recursive tree of ``commit``.

    ``ls-tree`` rather than a filesystem walk, so symlink (120000), gitlink
    (160000) and executable (100755) modes stay visible as data."""
    raw = _git(repo_root, ["ls-tree", "-r", "-z", commit])
    entries: dict[str, tuple[str, str, str]] = {}
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        meta, _, path = chunk.partition(b"\t")
        fields = meta.decode("utf-8", "surrogateescape").split(" ")
        if len(fields) != 3 or not path:
            raise M3FValidationError(f"unparsable ls-tree entry: {chunk!r}")
        mode, otype, sha = fields
        entries[path.decode("utf-8", "surrogateescape")] = (mode, otype, sha)
    return entries


def _name_status(repo_root: Path, parent: str, head: str) -> list[tuple[str, str]]:
    raw = _git(
        repo_root, ["diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", parent, head]
    )
    fields = [f for f in raw.split(b"\0") if f]
    if len(fields) % 2:
        raise M3FValidationError("git diff --name-status produced an odd field count")
    out: list[tuple[str, str]] = []
    for i in range(0, len(fields), 2):
        status = fields[i].decode("utf-8", "surrogateescape")
        path = fields[i + 1].decode("utf-8", "surrogateescape")
        out.append((status, path))
    return out


def _raw_ordinal(path: str) -> int | None:
    match = re.search(r"_(\d{4})_\d{8}_\d{8}\.json\Z", path)
    return int(match.group(1)) if match else None


def derive_binding(
    repo_root: str | Path, *, proposal_id: str, parent: str, head: str
) -> dict[str, Any]:
    """Re-derive the twelve binding fields from git alone.

    Takes commits and an identity — never a member list, never a pin map. There
    is no argument through which a record could widen the set it describes."""
    root = Path(repo_root)
    if not _PROPOSAL_ID_RE.fullmatch(proposal_id):
        raise M3FValidationError(f"malformed proposal id: {proposal_id!r}")
    for label, commit in (("parent", parent), ("head", head)):
        otype = _git(root, ["cat-file", "-t", commit]).decode().strip()
        if otype != "commit":
            raise M3FValidationError(f"{label} {commit[:12]}… is a {otype}, not a commit")
    if parent == head:
        raise M3FValidationError("proposal head equals its own parent")

    head_tree = _ls_tree(root, head)
    changed = _name_status(root, parent, head)
    numstat = _git(root, ["diff", "--numstat", "-z", "--no-renames", parent, head]).decode(
        "utf-8", "surrogateescape"
    )

    members: list[dict[str, Any]] = []
    for status, path in sorted(changed, key=lambda item: item[1]):
        role = _classify(path, proposal_id)
        if status not in {"A", "M"}:
            raise M3FValidationError(f"{path}: status {status!r} (only A/M are legal)")
        entry = head_tree.get(path)
        if entry is None:
            raise M3FValidationError(f"changed path is absent from the proposal tree: {path}")
        mode, otype, obj_sha = entry
        if otype != "blob" or mode != _ALLOWED_MODE:
            raise M3FValidationError(f"{path}: unlawful object {otype}/{mode}")
        blob = _git(root, ["cat-file", "blob", obj_sha])
        member: dict[str, Any] = {
            "byte_length": len(blob),
            "mode": mode,
            "object_type": otype,
            "path": path,
            "role": role,
            "sha256": _domain_sha256("m3e/proposal_file_policy/blob", {"bytes": blob.hex()}),
        }
        ordinal = _raw_ordinal(path)
        if ordinal is not None:
            member["acquisition_ordinal"] = ordinal
        members.append(member)
    members.sort(key=lambda m: str(m["path"]))
    paths = [str(m["path"]) for m in members]
    roles = {str(m["path"]): str(m["role"]) for m in members}

    return {
        "file_set_policy_id": EXPECTED_POLICY_ID,
        "binding_schema_version": EXPECTED_BINDING_SCHEMA_VERSION,
        "proposal_parent_commit": parent,
        "proposal_commit": head,
        "proposal_tree_sha256": _domain_sha256(
            _D_TREE,
            {
                "entries": [
                    {"mode": m, "path": p, "sha": s, "type": t}
                    for p, (m, t, s) in sorted(head_tree.items())
                ]
            },
        ),
        "proposal_diff_name_status_sha256": _domain_sha256(
            _D_NAME_STATUS,
            {"name_status": [[s, p] for s, p in sorted(changed, key=lambda i: i[1])]},
        ),
        "proposal_diff_numstat_sha256": _domain_sha256(_D_NUMSTAT, {"numstat": numstat}),
        "allowed_member_count": len(paths),
        "allowed_member_paths_sha256": _digest_paths(paths),
        "manifest_member_paths_sha256": _digest_paths(
            [p for p in paths if roles[p] in _MANIFEST_ROLES]
        ),
        "raw_member_paths_sha256": _digest_paths([p for p in paths if roles[p] in _RAW_ROLES]),
        "governance_member_paths_sha256": _digest_paths(
            [p for p in paths if roles[p] in _GOVERNANCE_ROLES]
        ),
        "proposal_bundle_sha256": _domain_sha256(_D_BUNDLE, {"members": members}),
    }


def verify_record_file_set(
    repo_root: str | Path, record: Mapping[str, Any], *, proposal_id: str
) -> dict[str, Any]:
    """Re-derive the record's ``file_set_binding`` from git and require equality.

    The commit pins come from the record — they are the proposal's identity, and
    the caller has already bound them into the acceptance chain. Everything else
    is recomputed. A record that names extra members, drops members, or relabels
    one cannot widen or narrow the set, because the set is never read from it."""
    binding = require_mapping(record.get("file_set_binding"), f"{proposal_id}.file_set_binding")
    if binding.get("file_set_policy_id") != EXPECTED_POLICY_ID:
        raise M3FValidationError(
            f"acceptance {proposal_id}: unknown file-set policy id "
            f"{binding.get('file_set_policy_id')!r}"
        )
    if binding.get("binding_schema_version") != EXPECTED_BINDING_SCHEMA_VERSION:
        raise M3FValidationError(f"acceptance {proposal_id}: unknown binding schema version")
    expected = derive_binding(
        repo_root,
        proposal_id=proposal_id,
        parent=_require_commit(
            f"{proposal_id}.proposal_parent_commit", binding.get("proposal_parent_commit")
        ),
        head=_require_commit(f"{proposal_id}.proposal_commit", binding.get("proposal_commit")),
    )
    for key in sorted(expected):
        if binding.get(key) != expected[key]:
            raise M3FValidationError(
                f"acceptance {proposal_id}: file-set binding disagrees with git at {key!r} "
                f"(record={binding.get(key)!r}, derived={expected[key]!r})"
            )
    unknown = sorted(set(binding) - set(expected))
    if unknown:
        raise M3FValidationError(
            f"acceptance {proposal_id}: file-set binding carries unknown field(s): {unknown}"
        )
    # The record's own commit pin must be the one the binding describes; otherwise
    # the binding could certify a different commit than the acceptance names.
    if record.get("proposal_head_commit") != binding.get("proposal_commit"):
        raise M3FValidationError(
            f"acceptance {proposal_id}: file-set binding certifies a different commit "
            f"than the record's proposal_head_commit"
        )
    if record.get("expected_parent_commit") != binding.get("proposal_parent_commit"):
        raise M3FValidationError(
            f"acceptance {proposal_id}: file-set binding certifies a different parent "
            f"than the record's expected_parent_commit"
        )
    return expected


__all__ = [
    "EXPECTED_BINDING_SCHEMA_VERSION",
    "EXPECTED_POLICY_ID",
    "derive_binding",
    "verify_record_file_set",
]
