"""Policy-derived closed set for a landed M3E update proposal (Auditor B, finding A-5).

Auditor B's finding A-5 — *"the closed set guarantee holds only against
non-resealing attackers"* — was demonstrated by adding one file to the accepted
proposal directory **and** adding that file's pin to the manifest / acceptance
record. All three independent readers passed it, because all three computed the
"closed set" the same way::

    live_files_on_disk == set(record["new_accepted"]["created"])

Both sides of that comparison are inside the blast radius of a resealing
attacker, so the equality proved only that the attacker was self-consistent. A
closed set derived from the thing being closed is not a closed set.

**The principle implemented here:** the proposal-controlled manifest may
*describe* its members, but POLICY decides which members are legal. A file must
never become acceptable merely because the attacker also added its hash. So the
permitted set is derived **independently of the manifest**:

1. the *changed set* is enumerated from git — ``git diff --name-status`` between
   the pinned trusted parent commit and the proposal head — never from a
   directory walk of the working tree and never from a pin map;
2. every member is then classified against a **fixed, source-pinned shape
   grammar** (:func:`_classify_path`, whose only inputs are a path and the
   proposal identity): exact allowed roots, exact basenames where fixed, exact
   extensions, exact expected change status;
3. the only content this module reads out of the proposal is the *update plans
   and acquisition receipts*, and it reads them solely to cross-check the raw
   response file names it already constrained by an independent regex — so a
   plan that declares an extra body still fails the name regex, and a body whose
   name passes the regex still fails unless the plan **and** the receipt both
   name it;
4. declared paths (manifest entries, ``created``/``state`` pin maps) are accepted
   as an argument only at the very end, and only ever *narrow* the outcome:
   :func:`derive_closed_set` — which computes the answer — cannot see them at
   all. Declaring a file is structurally incapable of admitting it.

Enforced rules (all fail closed, all independent of the manifest):

* exact allowed roots ``research/m3d/`` and ``research/m3e/`` — nothing else, ever;
* only ``A``/``M`` statuses (no delete, rename, copy, typechange, unmerged);
* the parent commit must be an ancestor of the proposal head;
* git mode must be exactly ``100644`` blob: no ``120000`` symlink, no ``160000``
  submodule/gitlink, no ``100755`` executable bit, no mode flip on a modified file;
* no Git-LFS pointer (``version https://git-lfs.github.com/spec/`` header);
* no path traversal, no absolute path, no backslash, no control character,
  no non-ASCII (which is what a Unicode-confusable filename is), no empty or
  ``.``/``..`` segment, no trailing dot/space;
* no case-fold collision, no NFC/NFD normalization collision, no duplicate
  normalized path — checked against **both** committed trees, so a case twin of
  a pre-existing file is caught even though nothing in the change set collides;
* no hidden/dotfile path segment (``.env``, ``.github/…``, ``…/.hidden/x.json``);
* no ``.yaml``/``.yml`` anywhere — an alternate workflow file is refused by
  extension before it is refused by root;
* no secret-shaped file (``.pem``, ``.key``, ``id_rsa``, …);
* no source/script file (``.py``, ``.sh``, …) and no source/test/tool/config
  mutation (``src/``, ``tests/``, ``tools/``, ``ci/``, ``.github/``, ``pyproject.toml``, …);
* extensions restricted to ``.json``/``.jsonl``;
* no unknown file: every path must match a shape rule for *this* proposal id;
* every fixed-basename member must be present (none missing), exactly one m3d raw
  bundle, exactly the two runner directories;
* the committed trees under the proposal directory and the raw bundle must contain
  nothing beyond the change set (a file that predates the range cannot hide there);
* raw responses: no extra, none missing, versus what the plans **and** receipts name,
  and byte-identical name sets across runner_a / runner_b;
* no untracked payload and no uncommitted drift under the allowed roots.

Nothing here reads a market value: every decision is a path, a git mode, a status
letter, or a file name. The module is data-governance only.

Known limit, stated rather than papered over: like every other verifier in this
stack, this one trusts git. An actor who can rewrite committed history can move
the parent pin itself. What it *does* remove is the far cheaper attack A-5 found —
appending a file plus its own pin — because the pin map is no longer consulted
when deciding what is legal.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    domain_sha256,
    require_list,
    require_mapping,
    require_str,
    strict_json_loads,
)

POLICY_KIND: Final[str] = "m3e_proposal_file_policy"
POLICY_SCHEMA_VERSION: Final[int] = 1
POLICY_DOMAIN: Final[str] = "m3e/proposal_file_policy"

#: The ONLY roots a landed proposal may touch. Not a default, not a starting
#: point: a path outside these is refused unconditionally, with no override.
ALLOWED_ROOTS: Final[tuple[str, ...]] = ("research/m3d/", "research/m3e/")

#: The only extensions a data-only proposal may carry.
ALLOWED_SUFFIXES: Final[tuple[str, ...]] = (".json", ".jsonl")

#: The only git file mode a proposal member may have.
ALLOWED_FILE_MODE: Final[str] = "100644"

_SYMLINK_MODE: Final[str] = "120000"
_GITLINK_MODE: Final[str] = "160000"
_EXECUTABLE_MODE: Final[str] = "100755"

#: Git-LFS pointer files begin with this exact header line.
_LFS_HEADER: Final[bytes] = b"version https://git-lfs.github.com/spec/"

#: Roots whose mutation is a code/config change, never a data proposal. Listed
#: explicitly so the refusal names the real problem instead of "unknown path".
_FORBIDDEN_MUTATION_PREFIXES: Final[tuple[str, ...]] = (
    ".github/",
    "ci/",
    "dist_private/",
    "docs/",
    "examples/",
    "governance/",
    "release/",
    "src/",
    "tests/",
    "tools/",
)
_FORBIDDEN_MUTATION_FILES: Final[frozenset[str]] = frozenset(
    {
        "CHANGELOG.md",
        "CITATION.cff",
        "README.md",
        "SECURITY.md",
        "pyproject.toml",
        "uv.lock",
    }
)

_WORKFLOW_SUFFIXES: Final[tuple[str, ...]] = (".yaml", ".yml")
_SECRET_SUFFIXES: Final[tuple[str, ...]] = (
    ".asc",
    ".crt",
    ".der",
    ".env",
    ".gpg",
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
    ".pgp",
    ".ppk",
)
_SECRET_BASENAMES: Final[frozenset[str]] = frozenset(
    {"authorized_keys", "credentials", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa", "netrc"}
)
_SOURCE_SUFFIXES: Final[tuple[str, ...]] = (
    ".bash",
    ".bat",
    ".c",
    ".cmd",
    ".dylib",
    ".exe",
    ".go",
    ".h",
    ".js",
    ".mjs",
    ".pl",
    ".ps1",
    ".pth",
    ".py",
    ".pyc",
    ".pyi",
    ".pyo",
    ".rb",
    ".rs",
    ".sh",
    ".so",
    ".ts",
    ".zsh",
)

#: ``<8-digit first open>-<8-digit exclusive end>-<16 hex idempotency prefix>``.
_PROPOSAL_ID_RE: Final[re.Pattern[str]] = re.compile(r"^\d{8}-\d{8}-[0-9a-f]{16}$")

#: The m3d raw bundle directory is the M3D attempt id, which must carry this
#: proposal's idempotency prefix — so a second bundle cannot ride along.
_BUNDLE_DIR_TEMPLATE: Final[str] = r"^coinbase-eth-usd-prospective-update-\d{8}-\d{8}-%s$"

#: Raw response bodies are named by :mod:`eth_research.m3e.update_plan`; the shape
#: is pinned here independently so a plan cannot legitimise an arbitrary name.
_RAW_RESPONSE_RE: Final[re.Pattern[str]] = re.compile(
    r"^coinbase-eth-usd-1d-update_\d{4}_\d{8}_\d{8}\.json$"
)

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_ASCII_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._/-]+$")

RUNNER_DIRS: Final[tuple[str, ...]] = ("runner_a", "runner_b")
RUNNER_PLAN_BASENAME: Final[str] = "update_plan.json"
RUNNER_RECEIPT_BASENAME: Final[str] = "acquisition_receipt.json"
BUNDLE_PLAN_BASENAME: Final[str] = "acquisition_plan.json"
BUNDLE_RECEIPT_BASENAME: Final[str] = "acquisition_receipt.json"

#: Roles a lawful member may hold. The role is assigned by policy, from the path
#: shape alone — never read out of the manifest.
ROLE_TRANSITIONED_STATE: Final[str] = "transitioned_state"
ROLE_UPDATE_ATTEMPTS: Final[str] = "update_attempts_ledger"
ROLE_BUNDLE_PLAN: Final[str] = "m3d_bundle_plan"
ROLE_BUNDLE_RECEIPT: Final[str] = "m3d_bundle_receipt"
ROLE_BUNDLE_RAW: Final[str] = "m3d_bundle_raw_response"
ROLE_PROPOSAL_DOC: Final[str] = "proposal_document"
ROLE_RUNNER_PLAN: Final[str] = "runner_update_plan"
ROLE_RUNNER_RECEIPT: Final[str] = "runner_acquisition_receipt"
ROLE_RUNNER_RAW: Final[str] = "runner_raw_response"

#: Pre-existing cohort files a proposal transitions. Modified, never added.
TRANSITIONED_STATE_PATHS: Final[tuple[str, ...]] = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/prospective_segments.jsonl",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
    "research/m3e/proposal_registry.jsonl",
)

#: The append-only attempt ledger: added by the first proposal, modified after.
UPDATE_ATTEMPTS_PATH: Final[str] = "research/m3d/update_attempts.jsonl"

#: Fixed-basename documents at the top level of a proposal directory.
PROPOSAL_DOCUMENT_BASENAMES: Final[tuple[str, ...]] = (
    "acquisition_comparison.json",
    "proposal_manifest.json",
    "update_transition.json",
)

_M3D_RAW_PREFIX: Final[str] = "research/m3d/raw/coinbase/"
_M3E_PROPOSALS_PREFIX: Final[str] = "research/m3e/proposals/"


class ProposalFilePolicyError(M3EValidationError):
    """A refused proposal file set. Always fail closed; never downgrade to a warning."""


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ChangedFile:
    """One member of the git-enumerated change set, after policy classification."""

    path: str
    status: str
    mode: str
    blob_sha: str
    role: str

    def as_json(self) -> dict[str, str]:
        return {
            "blob_sha": self.blob_sha,
            "mode": self.mode,
            "path": self.path,
            "role": self.role,
            "status": self.status,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class VerifiedProposalFiles:
    """The verified closed set plus the exact ``--name-status`` mapping.

    Every field here is derived from git and source-pinned policy. Nothing in it
    was read out of a proposal manifest or a pin map.
    """

    proposal_id: str
    parent_commit: str
    head_commit: str
    files: tuple[ChangedFile, ...]

    @property
    def closed_set(self) -> tuple[str, ...]:
        """The sorted, policy-verified permitted paths."""
        return tuple(entry.path for entry in self.files)

    @property
    def name_status(self) -> tuple[tuple[str, str], ...]:
        """The exact ``git diff --name-status`` mapping, as ``(status, path)`` pairs."""
        return tuple((entry.status, entry.path) for entry in self.files)

    @property
    def name_status_map(self) -> dict[str, str]:
        """``{path: status}`` — convenient for binding into a JSON record."""
        return {entry.path: entry.status for entry in self.files}

    @property
    def added(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.files if entry.status == "A")

    @property
    def modified(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.files if entry.status == "M")

    def paths_with_role(self, role: str) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.files if entry.role == role)

    @property
    def raw_response_paths(self) -> tuple[str, ...]:
        return tuple(
            entry.path for entry in self.files if entry.role in {ROLE_RUNNER_RAW, ROLE_BUNDLE_RAW}
        )

    def as_binding(self) -> dict[str, Any]:
        """A canonical, self-hashed binding for the acceptance record.

        The caller stores this verbatim. Because ``policy_digest`` covers the
        closed set *and* the commit pins *and* the policy version, a later reseal
        that grows the set has to change the digest, and the digest is derived
        from git, not from the record.
        """
        body: dict[str, Any] = {
            "added_count": len(self.added),
            "closed_set": list(self.closed_set),
            "file_count": len(self.files),
            "files": [entry.as_json() for entry in self.files],
            "head_commit": self.head_commit,
            "kind": POLICY_KIND,
            "modified_count": len(self.modified),
            "name_status": self.name_status_map,
            "parent_commit": self.parent_commit,
            "policy_schema_version": POLICY_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "schema_version": POLICY_SCHEMA_VERSION,
        }
        body["policy_digest"] = domain_sha256(POLICY_DOMAIN, body)
        # Round-trip guard: the binding must be canonical-JSON serialisable.
        canonical_json_bytes(body)
        return body


# ---------------------------------------------------------------------------
# git plumbing (argv arrays only — never a shell string)
# ---------------------------------------------------------------------------


def _git(repo_root: Path, argv: Sequence[str]) -> bytes:
    """Run ``git`` with an argv array. No shell, no interpolation, ever."""
    command = ["git", "-C", str(repo_root), *argv]
    try:
        completed = subprocess.run(  # fixed argv array, never a shell string
            command,
            capture_output=True,
            check=False,
        )
    except OSError as error:  # pragma: no cover - git missing is environmental
        raise ProposalFilePolicyError(f"git is unavailable: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ProposalFilePolicyError(f"git {' '.join(argv)} failed: {detail}")
    return completed.stdout


def _require_commit(repo_root: Path, label: str, value: object) -> str:
    text = require_str(label, value).strip()
    if not _COMMIT_RE.fullmatch(text):
        raise ProposalFilePolicyError(f"{label}: not a full 40-hex commit sha: {text!r}")
    resolved = _git(repo_root, ["rev-parse", "--verify", "--quiet", f"{text}^{{commit}}"])
    resolved_text = resolved.decode("ascii", "replace").strip()
    if resolved_text != text:
        raise ProposalFilePolicyError(f"{label}: {text} does not resolve to itself in this repo")
    return text


def _diff_name_status(repo_root: Path, parent: str, head: str) -> list[tuple[str, str]]:
    """``git diff --name-status`` as ``(status, path)``, NUL-delimited, renames off."""
    raw = _git(
        repo_root,
        ["diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", parent, head],
    )
    fields = [field for field in raw.split(b"\0") if field != b""]
    if len(fields) % 2 != 0:
        raise ProposalFilePolicyError("git diff --name-status produced an odd field count")
    entries: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        status = fields[index].decode("utf-8", "surrogateescape")
        path = fields[index + 1].decode("utf-8", "surrogateescape")
        entries.append((status, path))
    return entries


def _ls_tree(repo_root: Path, commit: str) -> dict[str, tuple[str, str, str]]:
    """``{path: (mode, type, object_sha)}`` for every entry in ``commit``.

    ``git ls-tree -r`` is used (not a filesystem walk) precisely so mode
    ``120000`` (symlink), ``160000`` (gitlink/submodule) and ``100755``
    (executable) are visible as data instead of being flattened by the checkout.
    """
    raw = _git(repo_root, ["ls-tree", "-r", "-z", commit])
    tree: dict[str, tuple[str, str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, path_bytes = record.partition(b"\t")
        parts = meta.split(b" ")
        if len(parts) != 3 or not path_bytes:
            raise ProposalFilePolicyError(f"unparseable ls-tree record: {record!r}")
        mode = parts[0].decode("ascii", "replace")
        obj_type = parts[1].decode("ascii", "replace")
        obj_sha = parts[2].decode("ascii", "replace")
        tree[path_bytes.decode("utf-8", "surrogateescape")] = (mode, obj_type, obj_sha)
    return tree


def _cat_blob(repo_root: Path, blob_sha: str) -> bytes:
    if not _COMMIT_RE.fullmatch(blob_sha):
        raise ProposalFilePolicyError(f"not a full 40-hex object id: {blob_sha!r}")
    return _git(repo_root, ["cat-file", "blob", blob_sha])


# ---------------------------------------------------------------------------
# Path policy — pure functions, no git, no manifest
# ---------------------------------------------------------------------------


def require_lawful_relpath(path: str) -> str:
    """Syntactic gate every proposal path must survive before it is classified.

    Rejects: absolute paths, backslashes, NUL/control characters, empty segments,
    ``.``/``..`` traversal segments, trailing dots or spaces, and any non-ASCII
    character (a Unicode-confusable filename is exactly a non-ASCII lookalike, so
    the whole class is refused rather than enumerated).
    """
    if not isinstance(path, str) or not path:
        raise ProposalFilePolicyError("proposal path is empty")
    if "\0" in path:
        raise ProposalFilePolicyError(f"proposal path contains NUL: {path!r}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        raise ProposalFilePolicyError(f"proposal path contains a control character: {path!r}")
    if not path.isascii():
        raise ProposalFilePolicyError(
            f"proposal path is not ASCII (Unicode-confusable filename refused): {path!r}"
        )
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise ProposalFilePolicyError(f"proposal path is absolute: {path!r}")
    if "\\" in path:
        raise ProposalFilePolicyError(f"proposal path contains a backslash: {path!r}")
    segments = path.split("/")
    for segment in segments:
        if segment == "":
            raise ProposalFilePolicyError(f"proposal path has an empty segment: {path!r}")
        if segment in {".", ".."}:
            raise ProposalFilePolicyError(
                f"proposal path contains a traversal segment {segment!r}: {path!r}"
            )
        if segment != segment.strip() or segment.endswith("."):
            raise ProposalFilePolicyError(
                f"proposal path segment has a trailing dot or space: {path!r}"
            )
    if not _ASCII_PATH_RE.fullmatch(path):
        raise ProposalFilePolicyError(
            f"proposal path uses a character outside [A-Za-z0-9._/-]: {path!r}"
        )
    return path


def require_no_path_collisions(changed: Iterable[str], universe: Iterable[str]) -> None:
    """No changed path may collide with a *different* path under case-fold or NFC/NFD.

    ``universe`` is every path in both committed trees, so a case twin of a file
    that already existed is caught even though nothing inside the change set
    collides with anything else inside it.
    """
    changed_set = set(changed)
    buckets: dict[tuple[str, str], set[str]] = {}
    for path in set(universe) | changed_set:
        for label, key in (
            ("case-fold", path.casefold()),
            ("NFC", unicodedata.normalize("NFC", path)),
            ("NFD", unicodedata.normalize("NFD", path)),
            ("NFKC", unicodedata.normalize("NFKC", path)),
        ):
            buckets.setdefault((label, key), set()).add(path)
    for (label, _key), members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        if not (members & changed_set):
            continue  # a pre-existing collision this proposal did not introduce
        raise ProposalFilePolicyError(
            f"proposal introduces a {label} path collision: {sorted(members)}"
        )


def _classify_path(path: str, proposal_id: str) -> str:
    """Return the policy role of ``path``, or refuse it.

    This function is the whole point of A-5: it takes a path and a proposal
    identity, and NOTHING else. There is no parameter through which a manifest,
    a pin map, or an attacker-supplied hash could reach it.
    """
    require_lawful_relpath(path)
    lowered = path.lower()

    # An alternate workflow is refused by extension first, so the refusal names
    # the real hazard rather than "outside the allowed roots".
    if lowered.endswith(_WORKFLOW_SUFFIXES):
        raise ProposalFilePolicyError(
            f"proposal adds a workflow/YAML file (never legal in a data proposal): {path}"
        )
    if any(segment.startswith(".") for segment in path.split("/")):
        raise ProposalFilePolicyError(f"proposal adds a hidden/dotfile path: {path}")
    basename = path.rsplit("/", 1)[-1]
    if lowered.endswith(_SECRET_SUFFIXES) or basename.lower() in _SECRET_BASENAMES:
        raise ProposalFilePolicyError(f"proposal adds a secret/key-shaped file: {path}")
    if lowered.endswith(_SOURCE_SUFFIXES):
        raise ProposalFilePolicyError(f"proposal adds a source/script file: {path}")
    if path.startswith(_FORBIDDEN_MUTATION_PREFIXES) or path in _FORBIDDEN_MUTATION_FILES:
        raise ProposalFilePolicyError(f"proposal mutates source/test/tool/config territory: {path}")
    if not path.startswith(ALLOWED_ROOTS):
        raise ProposalFilePolicyError(
            f"proposal path is outside the allowed roots {list(ALLOWED_ROOTS)}: {path}"
        )
    if not path.endswith(ALLOWED_SUFFIXES):
        raise ProposalFilePolicyError(
            f"proposal path has a disallowed extension (want {list(ALLOWED_SUFFIXES)}): {path}"
        )

    if path in TRANSITIONED_STATE_PATHS:
        return ROLE_TRANSITIONED_STATE
    if path == UPDATE_ATTEMPTS_PATH:
        return ROLE_UPDATE_ATTEMPTS

    bundle_re = re.compile(_BUNDLE_DIR_TEMPLATE % re.escape(proposal_id[-16:]))
    if path.startswith(_M3D_RAW_PREFIX):
        tail = path[len(_M3D_RAW_PREFIX) :].split("/")
        if len(tail) != 2:
            raise ProposalFilePolicyError(f"unknown file under the m3d raw root: {path}")
        bundle, name = tail
        if not bundle_re.fullmatch(bundle):
            raise ProposalFilePolicyError(
                f"raw bundle directory does not belong to proposal {proposal_id}: {path}"
            )
        if name == BUNDLE_PLAN_BASENAME:
            return ROLE_BUNDLE_PLAN
        if name == BUNDLE_RECEIPT_BASENAME:
            return ROLE_BUNDLE_RECEIPT
        if _RAW_RESPONSE_RE.fullmatch(name):
            return ROLE_BUNDLE_RAW
        raise ProposalFilePolicyError(f"unknown file in the m3d raw bundle: {path}")

    if path.startswith(_M3E_PROPOSALS_PREFIX):
        tail = path[len(_M3E_PROPOSALS_PREFIX) :].split("/")
        if tail[0] != proposal_id:
            raise ProposalFilePolicyError(
                f"file belongs to a different proposal than {proposal_id}: {path}"
            )
        rest = tail[1:]
        if len(rest) == 1:
            if rest[0] in PROPOSAL_DOCUMENT_BASENAMES:
                return ROLE_PROPOSAL_DOC
            raise ProposalFilePolicyError(f"unknown file in the proposal directory: {path}")
        if len(rest) == 2:
            runner, name = rest
            if runner not in RUNNER_DIRS:
                raise ProposalFilePolicyError(
                    f"unknown runner directory (want {list(RUNNER_DIRS)}): {path}"
                )
            if name == RUNNER_PLAN_BASENAME:
                return ROLE_RUNNER_PLAN
            if name == RUNNER_RECEIPT_BASENAME:
                return ROLE_RUNNER_RECEIPT
            if _RAW_RESPONSE_RE.fullmatch(name):
                return ROLE_RUNNER_RAW
            raise ProposalFilePolicyError(f"unknown file in a runner directory: {path}")
        raise ProposalFilePolicyError(f"proposal directory is nested too deeply: {path}")

    raise ProposalFilePolicyError(f"unknown file (no policy rule admits it): {path}")


def is_permitted_path(path: str, proposal_id: str) -> bool:
    """``True`` when policy alone admits ``path`` for ``proposal_id``.

    Deliberately total and side-effect free: a caller cannot pass a manifest, a
    pin map, or a hash, so no file can become permitted by being declared.
    """
    try:
        _classify_path(path, proposal_id)
    except ProposalFilePolicyError:
        return False
    return True


def _expected_status(role: str) -> frozenset[str]:
    if role == ROLE_TRANSITIONED_STATE:
        return frozenset({"M"})
    if role == ROLE_UPDATE_ATTEMPTS:
        return frozenset({"A", "M"})
    return frozenset({"A"})


# ---------------------------------------------------------------------------
# Raw-response cross-check (plans and receipts, never the manifest)
# ---------------------------------------------------------------------------


def _declared_raw_names(repo_root: Path, blob_sha: str, label: str, key: str) -> tuple[str, ...]:
    """Raw body names a plan (``windows``) or a receipt (``responses``) declares."""
    payload = strict_json_loads(_cat_blob(repo_root, blob_sha))
    document = require_mapping(label, payload)
    rows = require_list(f"{label}.{key}", document.get(key))
    names: list[str] = []
    for index, row in enumerate(rows):
        entry = require_mapping(f"{label}.{key}[{index}]", row)
        name = require_str(f"{label}.{key}[{index}].raw_filename", entry.get("raw_filename"))
        if not _RAW_RESPONSE_RE.fullmatch(name):
            raise ProposalFilePolicyError(
                f"{label} declares a raw body whose name policy refuses: {name!r}"
            )
        names.append(name)
    if len(set(names)) != len(names):
        raise ProposalFilePolicyError(f"{label} declares a duplicate raw body name")
    if not names:
        raise ProposalFilePolicyError(f"{label} declares no raw body")
    return tuple(sorted(names))


def _check_raw_group(
    repo_root: Path,
    *,
    label: str,
    plan_blob: str,
    receipt_blob: str,
    observed: set[str],
) -> tuple[str, ...]:
    plan_names = _declared_raw_names(repo_root, plan_blob, f"{label} update plan", "windows")
    receipt_names = _declared_raw_names(
        repo_root, receipt_blob, f"{label} acquisition receipt", "responses"
    )
    if plan_names != receipt_names:
        raise ProposalFilePolicyError(
            f"{label}: the plan and the receipt name different raw bodies "
            f"(plan={list(plan_names)}, receipt={list(receipt_names)})"
        )
    declared = set(plan_names)
    extra = sorted(observed - declared)
    missing = sorted(declared - observed)
    if extra:
        raise ProposalFilePolicyError(
            f"{label}: raw response not declared by the update plan or receipt: {extra}"
        )
    if missing:
        raise ProposalFilePolicyError(f"{label}: declared raw response is missing: {missing}")
    return plan_names


# ---------------------------------------------------------------------------
# The derivation: git + policy only
# ---------------------------------------------------------------------------


def derive_closed_set(
    repo_root: str | Path,
    *,
    proposal_id: str,
    parent_commit: str,
    head_commit: str,
    check_worktree: bool = True,
) -> VerifiedProposalFiles:
    """Derive the permitted set from git and source-pinned policy.

    This function takes **no** manifest, **no** pin map, and **no** declared path
    list. That is not an oversight — it is finding A-5's fix expressed in the
    signature: there is no channel through which declaring a file could admit it.
    """
    root = Path(repo_root)
    identity = require_str("proposal_id", proposal_id)
    if not _PROPOSAL_ID_RE.fullmatch(identity):
        raise ProposalFilePolicyError(f"proposal_id has an unlawful shape: {identity!r}")

    parent = _require_commit(root, "parent_commit", parent_commit)
    head = _require_commit(root, "head_commit", head_commit)
    if parent == head:
        raise ProposalFilePolicyError("parent_commit and head_commit are the same commit")
    ancestry = subprocess.run(  # fixed argv array, never a shell string
        ["git", "-C", str(root), "merge-base", "--is-ancestor", parent, head],
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ProposalFilePolicyError(
            f"parent_commit {parent[:12]} is not an ancestor of head_commit {head[:12]}"
        )

    entries = _diff_name_status(root, parent, head)
    if not entries:
        raise ProposalFilePolicyError("the proposal range changes no file at all")
    head_tree = _ls_tree(root, head)
    parent_tree = _ls_tree(root, parent)

    # --- phase 1: status alphabet -----------------------------------------
    seen: set[str] = set()
    for status, path in entries:
        if status not in {"A", "M"}:
            raise ProposalFilePolicyError(
                f"unlawful change status {status!r} (only A/M are legal): {path}"
            )
        if path in seen:
            raise ProposalFilePolicyError(f"duplicate entry in the change set: {path}")
        seen.add(path)

    # --- phase 2: git modes and object types ------------------------------
    for _status, path in sorted(entries, key=lambda item: item[1]):
        record = head_tree.get(path)
        if record is None:
            raise ProposalFilePolicyError(f"changed path is absent from the head tree: {path}")
        mode, obj_type, _sha = record
        if mode == _SYMLINK_MODE:
            raise ProposalFilePolicyError(f"proposal adds a symlink (mode 120000): {path}")
        if mode == _GITLINK_MODE or obj_type == "commit":
            raise ProposalFilePolicyError(
                f"proposal adds a submodule/gitlink (mode 160000): {path}"
            )
        if mode == _EXECUTABLE_MODE:
            raise ProposalFilePolicyError(f"proposal adds an executable file (mode 100755): {path}")
        if mode != ALLOWED_FILE_MODE or obj_type != "blob":
            raise ProposalFilePolicyError(
                f"proposal member has an unlawful git mode/type {mode}/{obj_type}: {path}"
            )
        previous = parent_tree.get(path)
        if previous is not None and previous[0] != ALLOWED_FILE_MODE:
            raise ProposalFilePolicyError(
                f"proposal flips the git mode of an existing file ({previous[0]}): {path}"
            )

    # --- phase 3: Git-LFS pointers ----------------------------------------
    for _status, path in sorted(entries, key=lambda item: item[1]):
        blob = _cat_blob(root, head_tree[path][2])
        if blob.startswith(_LFS_HEADER):
            raise ProposalFilePolicyError(
                f"proposal member is a Git-LFS pointer, not committed content: {path}"
            )

    # --- phase 4a: path syntax --------------------------------------------
    for _status, path in sorted(entries, key=lambda item: item[1]):
        require_lawful_relpath(path)

    # --- phase 4b: collisions against BOTH committed trees ----------------
    require_no_path_collisions(
        (path for _status, path in entries),
        set(head_tree) | set(parent_tree),
    )

    # --- phase 4c: classification against the fixed shape grammar ---------
    files: list[ChangedFile] = []
    for status, path in sorted(entries, key=lambda item: item[1]):
        role = _classify_path(path, identity)
        allowed_status = _expected_status(role)
        if status not in allowed_status:
            raise ProposalFilePolicyError(
                f"{path}: status {status!r} is unlawful for role {role!r} "
                f"(want {sorted(allowed_status)})"
            )
        if status == "A" and path in parent_tree:
            raise ProposalFilePolicyError(f"{path}: reported added but present at the parent")
        if status == "M" and path not in parent_tree:
            raise ProposalFilePolicyError(f"{path}: reported modified but absent at the parent")
        mode, _type, blob_sha = head_tree[path]
        files.append(ChangedFile(path=path, status=status, mode=mode, blob_sha=blob_sha, role=role))

    by_role: dict[str, list[ChangedFile]] = {}
    for entry in files:
        by_role.setdefault(entry.role, []).append(entry)
    paths = {entry.path for entry in files}

    # --- phase 5: nothing missing -----------------------------------------
    required = set(TRANSITIONED_STATE_PATHS) | {UPDATE_ATTEMPTS_PATH}
    required |= {
        f"{_M3E_PROPOSALS_PREFIX}{identity}/{name}" for name in PROPOSAL_DOCUMENT_BASENAMES
    }
    for runner in RUNNER_DIRS:
        required |= {
            f"{_M3E_PROPOSALS_PREFIX}{identity}/{runner}/{RUNNER_PLAN_BASENAME}",
            f"{_M3E_PROPOSALS_PREFIX}{identity}/{runner}/{RUNNER_RECEIPT_BASENAME}",
        }
    absent = sorted(required - paths)
    if absent:
        raise ProposalFilePolicyError(f"proposal is missing required members: {absent}")

    bundles = {
        entry.path[len(_M3D_RAW_PREFIX) :].split("/")[0]
        for entry in files
        if entry.role in {ROLE_BUNDLE_PLAN, ROLE_BUNDLE_RECEIPT, ROLE_BUNDLE_RAW}
    }
    if len(bundles) != 1:
        raise ProposalFilePolicyError(
            f"a proposal carries exactly one m3d raw bundle, found {sorted(bundles)}"
        )
    bundle = next(iter(bundles))
    for role in (ROLE_BUNDLE_PLAN, ROLE_BUNDLE_RECEIPT):
        if len(by_role.get(role, [])) != 1:
            raise ProposalFilePolicyError(f"the m3d raw bundle needs exactly one {role}")

    # --- phase 6: the committed trees hide nothing outside the range ------
    for prefix, label in (
        (f"{_M3E_PROPOSALS_PREFIX}{identity}/", "proposal directory"),
        (f"{_M3D_RAW_PREFIX}{bundle}/", "m3d raw bundle"),
    ):
        preexisting = sorted(path for path in parent_tree if path.startswith(prefix))
        if preexisting:
            raise ProposalFilePolicyError(
                f"{label} already existed at the parent commit: {preexisting}"
            )
        stray = sorted(path for path in head_tree if path.startswith(prefix) and path not in paths)
        if stray:
            raise ProposalFilePolicyError(
                f"{label} in the head tree holds files outside the change set: {stray}"
            )

    # --- phase 7: raw responses vs the plans AND the receipts --------------
    runner_raw_sets: dict[str, tuple[str, ...]] = {}
    for runner in RUNNER_DIRS:
        prefix = f"{_M3E_PROPOSALS_PREFIX}{identity}/{runner}/"
        observed = {
            entry.path[len(prefix) :]
            for entry in by_role.get(ROLE_RUNNER_RAW, [])
            if entry.path.startswith(prefix)
        }
        plan_blob = head_tree[f"{prefix}{RUNNER_PLAN_BASENAME}"][2]
        receipt_blob = head_tree[f"{prefix}{RUNNER_RECEIPT_BASENAME}"][2]
        runner_raw_sets[runner] = _check_raw_group(
            root,
            label=f"{identity}/{runner}",
            plan_blob=plan_blob,
            receipt_blob=receipt_blob,
            observed=observed,
        )
    if len(set(runner_raw_sets.values())) != 1:
        raise ProposalFilePolicyError(
            f"the runners carry different raw response sets: {runner_raw_sets}"
        )

    bundle_prefix = f"{_M3D_RAW_PREFIX}{bundle}/"
    bundle_observed = {
        entry.path[len(bundle_prefix) :] for entry in by_role.get(ROLE_BUNDLE_RAW, [])
    }
    bundle_names = _check_raw_group(
        root,
        label=f"m3d bundle {bundle}",
        plan_blob=head_tree[f"{bundle_prefix}{BUNDLE_PLAN_BASENAME}"][2],
        receipt_blob=head_tree[f"{bundle_prefix}{BUNDLE_RECEIPT_BASENAME}"][2],
        observed=bundle_observed,
    )
    if bundle_names != runner_raw_sets[RUNNER_DIRS[0]]:
        raise ProposalFilePolicyError(
            "the m3d raw bundle and the runners carry different raw response sets"
        )

    # --- phase 8: no untracked payload, no uncommitted drift ---------------
    if check_worktree:
        _require_clean_allowed_roots(root)

    return VerifiedProposalFiles(
        proposal_id=identity,
        parent_commit=parent,
        head_commit=head,
        files=tuple(files),
    )


def _require_clean_allowed_roots(repo_root: Path) -> None:
    """No untracked file and no uncommitted change may sit under the allowed roots."""
    roots = [root.rstrip("/") for root in ALLOWED_ROOTS]
    raw = _git(
        repo_root,
        ["status", "--porcelain", "-z", "--untracked-files=all", "--", *roots],
    )
    dirty = [
        record.decode("utf-8", "surrogateescape") for record in raw.split(b"\0") if record.strip()
    ]
    if dirty:
        raise ProposalFilePolicyError(
            f"untracked or uncommitted payload under {roots}: {sorted(dirty)}"
        )


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def verify_proposal_file_policy(
    repo_root: str | Path,
    *,
    proposal_id: str,
    parent_commit: str,
    head_commit: str,
    declared_paths: Mapping[str, Iterable[str]] | None = None,
    require_full_cover: bool = True,
    check_worktree: bool = True,
) -> VerifiedProposalFiles:
    """Verify a landed proposal's file set and return the closed set + name-status.

    ``declared_paths`` maps a label (``"manifest"``, ``"created_pins"``,
    ``"state_pins"``, …) to the paths that document names. It is checked
    **against** the independently derived closed set and can only ever narrow the
    outcome:

    * a declared path outside the closed set is a hard refusal — this is finding
      A-5: adding a file's pin does not make the file legal;
    * with ``require_full_cover`` (default), the union of the declared groups must
      also cover the closed set exactly, so a document cannot silently *omit* a
      member either.

    The closed set itself is computed by :func:`derive_closed_set`, which cannot
    see ``declared_paths`` at all.
    """
    verified = derive_closed_set(
        repo_root,
        proposal_id=proposal_id,
        parent_commit=parent_commit,
        head_commit=head_commit,
        check_worktree=check_worktree,
    )
    if declared_paths is None:
        return verified

    closed = set(verified.closed_set)
    union: set[str] = set()
    for label in sorted(declared_paths):
        declared = {
            require_str(f"declared_paths[{label}] entry", item) for item in declared_paths[label]
        }
        outside = sorted(declared - closed)
        if outside:
            raise ProposalFilePolicyError(
                f"declared_paths[{label!r}] names paths outside the policy-derived closed "
                f"set (declaring a file does NOT make it legal): {outside}"
            )
        union |= declared
    if require_full_cover:
        uncovered = sorted(closed - union)
        if uncovered:
            raise ProposalFilePolicyError(
                f"declared paths do not cover the closed set; undeclared members: {uncovered}"
            )
    return verified


__all__ = [
    "ALLOWED_FILE_MODE",
    "ALLOWED_ROOTS",
    "ALLOWED_SUFFIXES",
    "BUNDLE_PLAN_BASENAME",
    "BUNDLE_RECEIPT_BASENAME",
    "POLICY_DOMAIN",
    "POLICY_KIND",
    "POLICY_SCHEMA_VERSION",
    "PROPOSAL_DOCUMENT_BASENAMES",
    "ROLE_BUNDLE_PLAN",
    "ROLE_BUNDLE_RAW",
    "ROLE_BUNDLE_RECEIPT",
    "ROLE_PROPOSAL_DOC",
    "ROLE_RUNNER_PLAN",
    "ROLE_RUNNER_RAW",
    "ROLE_RUNNER_RECEIPT",
    "ROLE_TRANSITIONED_STATE",
    "ROLE_UPDATE_ATTEMPTS",
    "RUNNER_DIRS",
    "RUNNER_PLAN_BASENAME",
    "RUNNER_RECEIPT_BASENAME",
    "TRANSITIONED_STATE_PATHS",
    "UPDATE_ATTEMPTS_PATH",
    "ChangedFile",
    "ProposalFilePolicyError",
    "VerifiedProposalFiles",
    "derive_closed_set",
    "is_permitted_path",
    "require_lawful_relpath",
    "require_no_path_collisions",
    "verify_proposal_file_policy",
]
