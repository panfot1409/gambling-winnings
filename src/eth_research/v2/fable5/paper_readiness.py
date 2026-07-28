"""Paper-readiness derivation — a pure, machine-readable gate with no forcing literal.

Paper trading may begin only when *every* gate below holds. Each gate is **derived from committed
bytes** under a repository root; none is a stored settable flag trusted on its own, and there is no
literal / environment variable / CLI flag / monkeypatchable setting / alternate builder that can
force ``paper_activation_authorized`` (or ``paper_trading_active`` or ``sell_ready``) true. The
load-bearing gate is ``eligible_paper_candidate_present``: it is read from the committed V2A and V2B
decision artifacts, both of which nominate zero candidates (``nominated_candidate_id == null``,
``eligible_candidate_ids == []``), so it derives **false** and cannot be flipped without a genuine,
separately-governed nomination. A rejected or null-result candidate is not eligible.

Given the accepted V2 state (zero nominated candidates; sealed ledgers byte-empty; no paper-release
freeze; no human activation approval; no paper record), the derived state is:
``platform_audit_complete`` / ``platform_hardened`` = true once the Fable 5 remediation state is
frozen, ``eligible_paper_candidate_present`` = false, ``paper_release_candidate_frozen`` = false,
``paper_activation_authorized`` = false, ``paper_trading_active`` = false, ``sell_ready`` = false.

This module reads only bytes; it evaluates no strategy, opens no sealed value, and mutates nothing.
"""

from __future__ import annotations

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

#: The gates whose conjunction IS paper-activation authorization, in fixed order.
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


def _read_json(root: Path, rel: str) -> dict[str, object] | None:
    """Read a governance artifact as a JSON object, or ``None`` — strictly, and no symlinks.

    Two hardening rules, both reproduced as live attacks before being fixed and both
    already standard elsewhere in this tree (``v2e/paper.py``, ``v2e/state.py``,
    ``m3f/validation.py``); this module was the outlier:

    * **A symlink is not the artifact.** ``Path.is_file()`` follows symlinks, so a
      ``repository_visibility.json`` pointing anywhere on disk read as a committed
      record. A governed artifact must be a regular file whose bytes are in the tree.
    * **Strict decoding.** ``json.loads`` silently keeps the *last* of duplicate keys,
      so ``{"observed_private": false, "observed_private": true}`` parsed as private.
      That is the same duplicate-key bypass that opened the containment gate;
      :func:`strict_json_loads` rejects it, along with non-finite numbers.

    Every rejection returns ``None``, which fails the reading gate closed.
    """
    path = root / rel
    if path.is_symlink() or not path.is_file():
        return None
    try:
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
    """
    return (root / rel).exists() or (root / rel).is_symlink()


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
    eligible_list = v2b_eligible if isinstance(v2b_eligible, list) else []
    return bool(v2a_nominee) or bool(v2b_nominee) or len(eligible_list) > 0


def _remediation_resolved(root: Path) -> tuple[bool, bool]:
    """(audit_complete, no_unresolved_class_abd) from the frozen remediation state, if present."""
    state = _read_json(root, _REMEDIATION_STATE)
    manifest = _read_json(root, _AUDIT_MANIFEST)
    if state is None or manifest is None:
        return False, False
    unresolved = state.get("unresolved_class_abd_count", 1)
    all_resolved = state.get("all_findings_resolved", False)
    no_unresolved = isinstance(unresolved, int) and unresolved == 0
    return bool(all_resolved), no_unresolved


def _sealed_untouched(root: Path) -> bool:
    for rel in _SEALED_LEDGERS:
        path = root / rel
        if not path.is_file() or path.stat().st_size != 0:
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
    if record.get("schema_version") != _VISIBILITY_SCHEMA_VERSION:
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

    if not all(
        isinstance(record.get(field), str) and record.get(field)
        for field in ("observed_at", "observed_via", "observed_by")
    ):
        return False

    # ``observed_at`` is the whole claim to freshness, so it must be a real instant and
    # not the string "soon". Parsed, not merely non-empty; an unparseable stamp is a
    # record that cannot be reasoned about and fails closed.
    stamp = str(record.get("observed_at"))
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


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
    authorized = all(gates[g] for g in PAPER_ACTIVATION_GATES)
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
