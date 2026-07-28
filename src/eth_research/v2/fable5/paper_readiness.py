"""Paper-readiness derivation — a pure, machine-readable gate with no forcing literal.

Paper trading may begin only when *every* gate below holds. Each gate is derived from **bytes on
disk** under a repository root; none is a stored settable flag trusted on its own, and no literal,
environment variable or CLI flag can force ``paper_activation_authorized`` (or
``paper_trading_active`` or ``sell_ready``) true.

Two limits on that sentence, both established by a read-only refuter against a running copy and
recorded here because the sentence previously overstated them:

* **"committed bytes" is really "working tree".** Nothing here consults git. A ``.gitignore``d,
  never-committed file that ``git status`` does not show will satisfy a presence gate. What
  actually binds these artifacts to the repository is the Fable 5 governed inventory (byte pins
  plus an added/unclassified check) and the source freeze — not this module.
* **"monkeypatchable" was too strong.** Rebinding a module-level name in a live interpreter does
  move the result: reassigning ``PAPER_ACTIVATION_GATES`` to ``()`` makes ``all(...)`` vacuously
  true, and reassigning ``ReadinessInputs`` flips ``sell_ready``. That requires code execution
  inside the process, which is a strictly larger capability than writing files, so it is not a
  gate bypass — but the module should not claim immunity it does not have.

``sell_ready`` is additionally **not** derived from ``repo_root`` at all: it comes from
``ReadinessInputs.current()``, a fixed constructor. It is ``False`` for an empty directory, for the
real repository, and for a fully forged tree alike. That is the safe direction, and it is stated
rather than left to look like a derivation.

The load-bearing gate is ``eligible_paper_candidate_present``: it is read from the committed V2A
and V2B decision artifacts, both of which nominate zero candidates (``nominated_candidate_id ==
null``, ``eligible_candidate_ids == []``), so it derives **false** and cannot be flipped without a
genuine, separately-governed nomination. A rejected or null-result candidate is not eligible — and
that is now enforced rather than assumed: an id must be a non-empty string, because ``[null]`` once
satisfied a bare length check and flipped three gates.

Given the accepted V2 state (zero nominated candidates; sealed ledgers byte-empty; no paper-release
freeze; no human activation approval; no paper record), the derived state is:
``platform_audit_complete`` / ``platform_hardened`` = true once the Fable 5 remediation state is
frozen, ``eligible_paper_candidate_present`` = false, ``paper_release_candidate_frozen`` = false,
``paper_activation_authorized`` = false, ``paper_trading_active`` = false, ``sell_ready`` = false.

This module reads only bytes; it evaluates no strategy, opens no sealed value, and mutates nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.v2c.readiness import ReadinessInputs, derive_sell_ready

PAPER_READINESS_RELPATH = "governance/v2/paper_readiness_state.json"
PAPER_READINESS_SCHEMA_VERSION = 1

# Committed evidence the derivation reads (read-only, accepted artifacts).
_V2A_RESULTS = "research/v2a/results.json"
_V2B_RESULTS = "research/v2b/v2b_results.json"
_SEALED_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

# Fable 5 / paper-release evidence whose presence WOULD advance a gate. Absent today; their
# absence is the honest evidence the gate is unmet. Producing one legitimately flips its gate.
_REMEDIATION_STATE = "governance/v2/fable5_remediation_state.json"
_AUDIT_MANIFEST = "governance/v2/fable5_audit_manifest.json"
_PAPER_RELEASE_FREEZE = "governance/v2/paper_release_freeze.json"
_PAPER_ACTIVATION_APPROVAL = "governance/v2/paper_activation_approval.json"
_PAPER_TRADING_RECORD = "governance/v2/paper_trading_record.json"

# A committed observation of real GitHub repository visibility, produced from the REST
# API rather than inferred from packaging metadata. See ``_repository_private``.
_REPOSITORY_VISIBILITY = "governance/v2f/repository_visibility.json"
_EXPECTED_REPOSITORY = "panfot1409/gambling-winnings"
_VISIBILITY_SCHEMA_VERSION = 1
#: The repository's GitHub creation instant, from the REST API. A visibility
#: observation cannot predate the repository it claims to describe.
_REPOSITORY_CREATED = datetime.fromisoformat("2026-07-11T00:22:16+00:00")

#: The gates whose conjunction IS paper-activation authorization, in fixed order.
#: This tuple exists ONLY to give ``blocking_gates`` a stable, readable order. It is NOT
#: the authority — see :data:`REQUIRED_PAPER_ACTIVATION_GATES` and :func:`_authorized`.
PAPER_ACTIVATION_GATES: tuple[str, ...] = (
    "platform_audit_complete",
    "platform_hardened",
    "no_unresolved_class_abd_finding",
    "eligible_paper_candidate_present",
    "candidate_lineage_valid",
    "strategy_specification_immutable",
    "paper_release_candidate_frozen",
    "paper_duration_and_success_criteria_preregistered",
    "human_activation_approval_recorded",
    "sealed_partitions_untouched",
    "repository_private",
)

#: The exact set of gate names that must ALL hold for paper activation. Authorization is
#: decided against this frozen set, never by reducing over a replaceable sequence.
#:
#: Why this is not simply ``all(gates[g] for g in PAPER_ACTIVATION_GATES)``: that form is
#: *vacuously true* over an empty collection. Rebinding the module-level name to ``()``
#: produced ``paper_activation_authorized = True`` with ``blocking_gates = ()`` while the
#: gate vector itself still reported unmet gates — a self-inconsistent authorization, and
#: exactly the shape of bug that reads as fine in review. Reducing over data that can be
#: replaced makes the *collection* the authority; naming the requirement makes the
#: *requirement* the authority.
REQUIRED_PAPER_ACTIVATION_GATES: frozenset[str] = frozenset(
    {
        "platform_audit_complete",
        "platform_hardened",
        "no_unresolved_class_abd_finding",
        "eligible_paper_candidate_present",
        "candidate_lineage_valid",
        "strategy_specification_immutable",
        "paper_release_candidate_frozen",
        "paper_duration_and_success_criteria_preregistered",
        "human_activation_approval_recorded",
        "sealed_partitions_untouched",
        "repository_private",
    }
)


def _authorized(gates: dict[str, bool]) -> bool:
    """True only if the gate vector is EXACTLY the required set and every value is ``True``.

    Four independent conditions, each of which alone refuses:

    * the requirement itself must be non-empty — an empty requirement authorizes nothing,
      which is what makes this immune to the vacuous-``all`` rewrite;
    * the delivered key set must equal the required set exactly — a missing gate cannot be
      skipped, and an *extra* gate is equally refused because it means the caller is not
      speaking the schema this function validates;
    * every value must be the ``True`` singleton — ``is True`` rather than truthiness, so
      ``1``, ``"yes"`` and a truthy object are all rejected;
    * the ordering tuple must agree with the required set, so the two cannot silently drift
      apart and leave ``blocking_gates`` describing a different question than authorization.

    This does not defend against arbitrary in-process code execution — an attacker who can
    rebind names can rebind this function too. That threat is addressed by source freeze,
    package verification and deployment isolation, not by anything written here.
    """
    if not REQUIRED_PAPER_ACTIVATION_GATES:
        return False
    if set(gates) != REQUIRED_PAPER_ACTIVATION_GATES:
        return False
    if set(PAPER_ACTIVATION_GATES) != REQUIRED_PAPER_ACTIVATION_GATES:
        return False
    return all(gates.get(name) is True for name in REQUIRED_PAPER_ACTIVATION_GATES)


class PaperReadinessError(RuntimeError):
    """The committed paper-readiness state disagrees with the derivation from bytes."""


@dataclass(frozen=True, slots=True)
class PaperReadinessState:
    schema_version: int
    gates: dict[str, bool]
    eligible_paper_candidate_present: bool
    paper_activation_authorized: bool
    paper_trading_active: bool
    sell_ready: bool
    blocking_gates: tuple[str, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "gates": dict(self.gates),
            "eligible_paper_candidate_present": self.eligible_paper_candidate_present,
            "paper_activation_authorized": self.paper_activation_authorized,
            "paper_trading_active": self.paper_trading_active,
            "sell_ready": self.sell_ready,
            "blocking_gates": list(self.blocking_gates),
        }


def _unlinked_regular_file(root: Path, rel: str) -> Path | None:
    """Return ``root/rel`` only if NO component of ``rel`` is a symlink and it is a file.

    Checking ``Path.is_symlink()`` on the assembled path tests the **final component
    only**. An auditor made ``governance/v2f`` a symlink to a directory elsewhere: the
    final component was then a perfectly ordinary regular file, the guard passed, and
    the gate read bytes from a path nobody reviews — ``git log`` on the governed path
    is empty, because the governed path is not where the bytes live. The attack is
    committable, too: git stores the directory as a mode-120000 entry.

    So every component is checked, from ``root`` down. ``root`` itself is not checked:
    the caller chose the tree, and repositories legitimately live under symlinked
    paths. What must not happen is a component *inside* the tree redirecting elsewhere.
    """
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def _read_json(root: Path, rel: str) -> dict[str, object] | None:
    """Read a governance artifact as a JSON object, or ``None`` — strictly, no symlinks.

    Two hardening rules, both reproduced as live attacks before being fixed and both
    already standard elsewhere in this tree (``v2e/paper.py``, ``v2e/state.py``,
    ``m3f/validation.py``); this module was the outlier:

    * **A symlink is not the artifact**, at any depth — see
      :func:`_unlinked_regular_file`.
    * **Strict decoding.** ``json.loads`` silently keeps the *last* of duplicate keys,
      so ``{"observed_private": false, "observed_private": true}`` parsed as private.
      That is the same duplicate-key bypass that opened the containment gate;
      :func:`strict_json_loads` rejects it, along with non-finite numbers.

    Every rejection returns ``None``, which fails the reading gate closed — including
    an unreadable file. ``OSError`` is caught around the path inspection too, not only
    around the read: a permission error while *stat-ing* the path used to propagate out
    of a function documented as never raising.
    """
    try:
        path = _unlinked_regular_file(root, rel)
        if path is None:
            return None
        data = strict_json_loads(path.read_bytes())
    except (StrictJSONError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _path_exists(root: Path, rel: str) -> bool:
    """True if *anything* is at ``rel`` — symlink, directory, malformed file included.

    Deliberately weaker than :func:`_read_json`, and used only for the paper-trading
    record. Presence of that record makes ``paper_trading_active`` **true**, so the
    conservative direction is inverted: corrupting the record must not be a way to
    report "not trading". Gates that must be *earned* keep the strict reader.

    Implemented with ``os.lstat`` rather than ``Path.exists() or Path.is_symlink()``,
    because both of those swallow a fixed set of errnos (``ENOENT``, ``ENOTDIR``,
    ``EBADF``, ``ELOOP``) and so cannot distinguish "absent" from "could not tell".
    ``lstat`` not ``stat``, so a broken symlink still counts as present.

    Only the two errnos that genuinely mean *nothing can be there* count as absent:
    ``ENOENT``, and ``ENOTDIR`` (a parent component is a regular file, so no child can
    exist). Every other ``OSError`` — ``ELOOP``, ``EACCES``, ``ENAMETOOLONG`` — means we
    failed to establish absence, and unestablished absence is reported as presence.

    Provenance, since it bears on how much this is worth: an auditor reported a 40-deep
    symlink chain making this return ``False`` "with the record readable on disk". A
    refuter showed the substance was wrong — at that chain length the record is not
    readable *through this path* either, and the realistic version of the attack
    collapses three other gates and is refused by the inventory's symlink check. So this
    is a correctness repair on an inverted-safety reader, not the closure of a live
    inversion. It is worth having anyway: a reader that cannot tell absence from failure
    should say so, and the cost is that an unreadable path now derives
    ``paper_trading_active = True``, which makes ``verify_paper_readiness`` fail loudly
    rather than pass quietly.
    """
    try:
        os.lstat(root / rel)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return True


def _nested_dict(obj: dict[str, object] | None, key: str) -> dict[str, object]:
    """Return ``obj[key]`` when it is itself a JSON object, else an empty dict (fail-closed)."""
    if obj is None:
        return {}
    value = obj.get(key)
    return value if isinstance(value, dict) else {}


def _eligible_candidate_present(root: Path) -> bool:
    """True only if the committed V2A/V2B decisions nominate at least one eligible candidate.

    Reads the accepted decision artifacts. V2A stores ``decision.nominated_candidate_id``; V2B
    stores ``result.decision.{nominated_candidate_id, eligible_candidate_ids}``. Any missing or
    malformed artifact fails closed to *not present*.
    """
    v2a = _read_json(root, _V2A_RESULTS)
    v2b = _read_json(root, _V2B_RESULTS)
    if v2a is None or v2b is None:
        return False
    v2a_nominee = _nested_dict(v2a, "decision").get("nominated_candidate_id")
    v2b_decision = _nested_dict(_nested_dict(v2b, "result"), "decision")
    v2b_nominee = v2b_decision.get("nominated_candidate_id")
    v2b_eligible = v2b_decision.get("eligible_candidate_ids")
    # Elements must be non-empty strings. `len(list) > 0` alone counted `[null]`,
    # `[false]`, `[0]` and `[""]` as eligible candidates — which is precisely the
    # "null-result candidate is not eligible" rule this module's docstring states,
    # broken by the module itself. A padding or placeholder list flipped three gates.
    eligible_list = v2b_eligible if isinstance(v2b_eligible, list) else []
    named = [c for c in eligible_list if isinstance(c, str) and c.strip()]
    return bool(v2a_nominee) or bool(v2b_nominee) or len(named) > 0


def _remediation_resolved(root: Path) -> tuple[bool, bool]:
    """(audit_complete, no_unresolved_class_abd) from the frozen remediation state, if present."""
    state = _read_json(root, _REMEDIATION_STATE)
    manifest = _read_json(root, _AUDIT_MANIFEST)
    if state is None or manifest is None:
        return False, False

    # Both fields are type-checked, and `bool` is excluded from the integer check.
    # Without this, a record whose literal text reads
    #   {"all_findings_resolved": "false", "unresolved_class_abd_count": false}
    # derived BOTH gates true: `bool("false")` is True, and `isinstance(False, int)`
    # is True with `False == 0`. A human reading that JSON would conclude the exact
    # opposite of what the code concluded. `_repository_private` already guarded
    # against this conflation; these two fields did not.
    all_resolved = state.get("all_findings_resolved")
    unresolved = state.get("unresolved_class_abd_count")
    no_unresolved = (
        isinstance(unresolved, int) and not isinstance(unresolved, bool) and unresolved == 0
    )
    return all_resolved is True, no_unresolved


def _sealed_untouched(root: Path) -> bool:
    """True only if all three sealed ledgers are byte-empty regular files, no symlinks.

    This used ``is_file()``/``stat()``, both of which follow symlinks — so replacing
    the ledgers with symlinks to one shared empty file reported them untouched. It is
    the same defect ``_read_json`` was hardened against, in the same module, and it
    guards the partition whose whole purpose is to be provably unopened.
    """
    for rel in _SEALED_LEDGERS:
        try:
            path = _unlinked_regular_file(root, rel)
            if path is None or path.stat().st_size != 0:
                return False
        except OSError:
            # Inspecting the path can itself fail (an unsearchable parent directory).
            # The resolution used to sit outside this try, so that raised out of a
            # function whose whole contract is to return a bool.
            return False
    return True


def _repository_private(root: Path) -> bool:
    """True only if a typed, attributed observation records this repository as private.

    This gate previously returned ``"Private :: Do Not Upload" in pyproject.toml``. That
    string is a **PyPI trove classifier**: it controls whether the Python Package Index
    rejects an upload, and carries no information at all about GitHub repository
    visibility. It was measured returning ``True`` while the GitHub API reported
    ``private: false`` — a Class A safety defect, since authorization is the conjunction
    of every gate and this was the one keeping paper trading off a public repository.
    The incident is recorded in ``docs/V2_PUBLIC_EXPOSURE_INCIDENT.md``.

    The replacement reads a visibility *observation* rather than a proxy for one. It is
    still not a live check — this module derives from committed bytes and must stay
    deterministic and offline — so the honest framing is: some named party observed the
    GitHub API at a stated time and committed what it said. Every one of those parts is
    required, because an unattributed or self-contradictory record is indistinguishable
    from a wish.

    Fail-closed in every direction: a missing record, a wrong ``kind``, a record for a
    different repository, a non-boolean ``observed_private``, a ``visibility`` string
    that disagrees with the boolean, or missing attribution all derive **false**.
    """
    record = _read_json(root, _REPOSITORY_VISIBILITY)
    if record is None:
        return False
    if record.get("kind") != "v2f_repository_visibility":
        return False
    # `!= 1` alone accepts True and 1.0, since both compare equal to 1. Same bool/int
    # conflation the observed_private check already guards against.
    schema_version = record.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != _VISIBILITY_SCHEMA_VERSION
    ):
        return False
    if record.get("repository") != _EXPECTED_REPOSITORY:
        return False

    observed_private = record.get("observed_private")
    if not isinstance(observed_private, bool) or not observed_private:
        return False
    # A half-updated record — boolean flipped, string left behind — is a lie in one of
    # its two halves. Require them to agree rather than picking a winner.
    if record.get("observed_visibility") != "private":
        return False

    # Attribution must be a real name, not a space. "an unattributed record is
    # indistinguishable from a wish" was the stated reason for these fields, and a
    # truthiness check let `observed_by=" "` satisfy it.
    if not all(
        isinstance(record.get(field), str) and len(str(record.get(field)).strip()) >= 2
        for field in ("observed_at", "observed_via", "observed_by")
    ):
        return False

    # ``observed_at`` is the whole claim to freshness, so it must be a real instant —
    # not the string "soon", and not a date-shaped string from year 1. Parsing alone
    # accepted "0001-01-01", "2026-W30-2" and bare "20260728"; requiring an explicit
    # UTC offset and a floor at the repository's creation kills all three.
    #
    # There is deliberately NO upper bound against "now": this derivation must stay
    # deterministic and offline, and comparing to a wall clock would make the same
    # bytes derive differently on different days. A future-dated record is therefore
    # accepted, and is part of the disclosed staleness gap rather than a separate one.
    stamp = str(record.get("observed_at"))
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return observed.tzinfo is not None and observed >= _REPOSITORY_CREATED


def derive_paper_readiness(repo_root: str | Path) -> PaperReadinessState:
    """Derive the paper-readiness state purely from committed bytes under ``repo_root``."""
    root = Path(repo_root)
    audit_complete, no_unresolved_abd = _remediation_resolved(root)
    eligible = _eligible_candidate_present(root)
    freeze_present = _read_json(root, _PAPER_RELEASE_FREEZE) is not None
    approval_present = _read_json(root, _PAPER_ACTIVATION_APPROVAL) is not None
    sealed_untouched = _sealed_untouched(root)
    private = _repository_private(root)

    # With no eligible candidate there is no lineage / spec / preregistered protocol to validate;
    # those gates derive false. They are never asserted true absent a real nominated candidate.
    gates: dict[str, bool] = {
        "platform_audit_complete": audit_complete,
        "platform_hardened": audit_complete and no_unresolved_abd,
        "no_unresolved_class_abd_finding": no_unresolved_abd,
        "eligible_paper_candidate_present": eligible,
        "candidate_lineage_valid": eligible,
        "strategy_specification_immutable": eligible,
        "paper_release_candidate_frozen": freeze_present and eligible,
        "paper_duration_and_success_criteria_preregistered": freeze_present and eligible,
        "human_activation_approval_recorded": approval_present,
        "sealed_partitions_untouched": sealed_untouched,
        "repository_private": private,
    }
    authorized = _authorized(gates)
    trading_active = _path_exists(root, _PAPER_TRADING_RECORD)
    sell_ready = derive_sell_ready(ReadinessInputs.current())
    blocking = tuple(g for g in PAPER_ACTIVATION_GATES if not gates[g])
    return PaperReadinessState(
        schema_version=PAPER_READINESS_SCHEMA_VERSION,
        gates=gates,
        eligible_paper_candidate_present=eligible,
        paper_activation_authorized=authorized,
        paper_trading_active=trading_active,
        sell_ready=sell_ready,
        blocking_gates=blocking,
    )


def verify_paper_readiness(
    repo_root: str | Path, committed: dict[str, object]
) -> PaperReadinessState:
    """Re-derive and prove the committed ``paper_readiness_state.json`` matches, failing closed.

    Also enforces the standing safety assertions regardless of the committed file: authorization,
    active trading, and sell-readiness must all be false.
    """
    derived = derive_paper_readiness(repo_root)
    problems: list[str] = []
    for key in ("paper_activation_authorized", "paper_trading_active", "sell_ready"):
        if committed.get(key) != getattr(derived, key):
            problems.append(
                f"{key}: committed {committed.get(key)!r} != derived {getattr(derived, key)!r}"
            )
    if (
        committed.get("eligible_paper_candidate_present")
        != derived.eligible_paper_candidate_present
    ):
        problems.append("eligible_paper_candidate_present disagrees with the committed decisions")
    if committed.get("gates") != derived.gates:
        problems.append("gate vector drift between committed state and derivation")
    # Standing safety net: these must never be true in this milestone.
    if derived.paper_activation_authorized:
        problems.append("paper_activation_authorized derived true (must be false)")
    if derived.paper_trading_active:
        problems.append("paper_trading_active derived true (must be false)")
    if derived.sell_ready:
        problems.append("sell_ready derived true (must be false)")
    if problems:
        raise PaperReadinessError(
            "paper-readiness verification failed:\n  - " + "\n  - ".join(problems)
        )
    return derived
