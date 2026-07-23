"""V2C section 35 (OQ-E2): the operational-qualification REPLACEMENT source freeze.

Proves the committed ``governance/v2c/oq_source_freeze.json`` is a pure, reproducible,
wall-clock-free binding of the *complete transitive* qualification-defining source plus the broader
V2C surface, that it carries the full OQ-E2 evidence set (schema 2, the replaced/superseded, the
supersession record, the runtime-contract identity, the pristine registry / sealed-ledger
preconditions, a domain-separated fingerprint, and a whole-body aggregate digest), that the frozen
source set is exactly the live OQ import closure (minus package shims and the freezer itself) plus a
documented set of deliberately-frozen extras, and that any drift -- a changed byte, a symlink, a
traversal, a duplicate, a missing member, a missing/absent supersession record -- is refused
fail-closed. Also proves the OQ-E2A activation anchor round-trips and rejects tampering.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2.strict import canonical_sha256, sha256_bytes
from eth_research.v2c.oq import freeze as F
from eth_research.v2c.oq.freeze import (
    EMPTY_SHA256,
    OQ_E2_ACTIVATION_RELPATH,
    OQ_E2_FREEZE_ID,
    OQ_SOURCE_FREEZE_RELPATH,
    PREMATURE_OQ_FREEZE_COMMIT,
    SUPERSEDED_FREEZE_ID,
    OQSourceFreezeError,
    build_oq_e2_activation,
    build_oq_source_freeze,
    oq_source_freeze_digest,
    render_oq_source_freeze_bytes,
    verify_oq_e2_activation,
    verify_oq_source_freeze,
    write_oq_e2_activation,
    write_oq_source_freeze,
)
from eth_research.v2c.oq.supersession import (
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
    append_supersession,
    read_supersession,
)

REPO = Path(__file__).resolve().parents[1]

# The frozen relpaths, read from the module's own committed set via a build against the real repo.
_FROZEN = build_oq_source_freeze(REPO)
_ALL_RELPATHS = tuple(_FROZEN["frozen_source_sha256"]) + tuple(_FROZEN["frozen_artifact_sha256"])

# --------------------------------------------------------------------------- #
# The OQ execution import closure (computed live, so the freeze scope cannot   #
# silently drift): the transitive eth_research.* imports of the OQ entry       #
# points, resolved to committed source files.                                 #
# --------------------------------------------------------------------------- #
_ENTRY_POINTS = (
    "eth_research.v2c.oq.cli",
    "eth_research.v2c.oq.run",
    "eth_research.v2c.oq.orchestrator",
    "eth_research.v2c.oq.oracle",
    "eth_research.v2c.oq.verify_archive",
    "eth_research.v2c.oq.finalize",
    "eth_research.v2c.oq.freeze",
    "eth_research.v2c.oq.protocol",
    "eth_research.v2c.oq.recovery",
)

#: Closure members deliberately NOT frozen: the two package ``__init__`` shims (no qualification
#: logic; the package version is bound separately) and ``freeze.py`` itself (a self-reference would
#: be circular).
_EXCLUSIONS = frozenset(
    {
        "src/eth_research/__init__.py",
        "src/eth_research/v2c/oq/__init__.py",
        "src/eth_research/v2c/oq/freeze.py",
    }
)

#: Members frozen deliberately though the OQ *runner* does not import them: the broader committed
#: V2C qualification-defining surface (the process-isolated buyer boundary + the V2A buyer artifacts
#: it drives, the prospective governance, the inactive activation template, the readiness
#: derivation) plus the durable-write helper. Every one is proven below to be genuinely outside the
#: execution closure, so it is an intentional addition, not an accidentally-included import.
_DELIBERATE_EXTRAS = frozenset(
    {
        "src/eth_research/_atomic.py",
        "src/eth_research/buyer/claims.py",
        "src/eth_research/buyer/contract.py",
        "src/eth_research/buyer/diligence.py",
        "src/eth_research/buyer/factsheet.py",
        "src/eth_research/buyer/gateway.py",
        "src/eth_research/buyer/redaction.py",
        "src/eth_research/buyer/scorecard.py",
        "src/eth_research/v2c/activation_template.py",
        "src/eth_research/v2c/buyer/boundary.py",
        "src/eth_research/v2c/buyer/framing.py",
        "src/eth_research/v2c/buyer/harness.py",
        "src/eth_research/v2c/buyer/isolation.py",
        "src/eth_research/v2c/maturity.py",
        "src/eth_research/v2c/proposal.py",
        "src/eth_research/v2c/proposal_generator.py",
        "src/eth_research/v2c/prospective.py",
        "src/eth_research/v2c/readiness.py",
    }
)


def _module_to_relpath(mod: str) -> str | None:
    parts = mod.split(".")
    f = REPO / "src" / Path(*parts).with_suffix(".py")
    if f.is_file():
        return str(f.relative_to(REPO))
    pkg = REPO / "src" / Path(*parts) / "__init__.py"
    if pkg.is_file():
        return str(pkg.relative_to(REPO))
    return None


def _oq_execution_closure() -> set[str]:
    """The ``src/eth_research/*.py`` set reachable by transitive import from the OQ entry points."""
    seen: set[str] = set()
    stack: list[str] = list(_ENTRY_POINTS)
    files: set[str] = set()
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        rel = _module_to_relpath(mod)
        if rel is None:
            continue
        files.add(rel)
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("eth_research"):
                        stack.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module or not node.module.startswith("eth_research"):
                    continue
                stack.append(node.module)
                for alias in node.names:
                    stack.append(f"{node.module}.{alias.name}")
    return {f for f in files if f.startswith("src/eth_research/")}


def _make_fake_repo(root: Path) -> None:
    """Materialize a self-consistent stub repo: every frozen member, the runtime contract, and a
    valid supersession ledger recording the premature freeze superseded, so the build succeeds."""
    for rel in _ALL_RELPATHS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"stub for {rel}\n", encoding="utf-8")
    rc = root / CANONICAL_RUNTIME_CONTRACT_RELPATH
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text("stub runtime contract\n", encoding="utf-8")
    append_supersession(
        root / OQ_SUPERSESSION_PATH,
        supersession_id="oq_source_freeze_supersession_001",
        superseded_commit=PREMATURE_OQ_FREEZE_COMMIT,
        superseded_freeze_relpath="governance/v2c/oq_source_freeze.json",
        superseded_freeze_artifact_sha256="a" * 64,
        registry_relpath="governance/v2c/oq_registry.jsonl",
        registry_byte_count=0,
        registry_sha256=EMPTY_SHA256,
        registry_event_count=0,
        sealed_ledger_sha256=dict.fromkeys(SEALED_LEDGER_RELPATHS, EMPTY_SHA256),
        generated_utc="2026-07-21T00:00:00+00:00",
        package_version=PACKAGE_VERSION,
    )


# --------------------------------------------------------------------------- #
# Reproduction + determinism                                                  #
# --------------------------------------------------------------------------- #
def test_committed_freeze_reproduces_from_live_source() -> None:
    verify_oq_source_freeze(REPO)  # must not raise
    committed = (REPO / OQ_SOURCE_FREEZE_RELPATH).read_bytes()
    assert committed == render_oq_source_freeze_bytes(build_oq_source_freeze(REPO))


def test_build_is_deterministic() -> None:
    assert build_oq_source_freeze(REPO) == build_oq_source_freeze(REPO)


def test_digest_helper_matches_build() -> None:
    assert oq_source_freeze_digest(REPO) == build_oq_source_freeze(REPO)["source_freeze_digest"]


# --------------------------------------------------------------------------- #
# The OQ-E2 evidence set (section 9B)                                         #
# --------------------------------------------------------------------------- #
def test_binds_the_full_e2_evidence_set() -> None:
    freeze = build_oq_source_freeze(REPO)
    assert freeze["schema_version"] == 2
    assert freeze["freeze_id"] == OQ_E2_FREEZE_ID
    assert freeze["replaces_freeze_id"] == SUPERSEDED_FREEZE_ID
    assert freeze["superseded_freeze_commit"] == PREMATURE_OQ_FREEZE_COMMIT
    assert freeze["package_version"] == PACKAGE_VERSION
    assert freeze["runtime_contract_relpath"] == CANONICAL_RUNTIME_CONTRACT_RELPATH
    assert freeze["runtime_contract_sha256"] == sha256_bytes(
        (REPO / CANONICAL_RUNTIME_CONTRACT_RELPATH).read_bytes()
    )
    assert freeze["expected_registry"] == {
        "relpath": "governance/v2c/oq_registry.jsonl",
        "sha256": EMPTY_SHA256,
        "byte_count": 0,
        "event_count": 0,
    }
    assert set(freeze["expected_sealed_ledgers"]) == set(SEALED_LEDGER_RELPATHS)
    for entry in freeze["expected_sealed_ledgers"].values():
        assert entry == {"sha256": EMPTY_SHA256, "byte_count": 0}
    # The supersession-record + superseded-artifact hashes are the committed ledger record's own.
    records = read_supersession(REPO / OQ_SUPERSESSION_PATH)
    rec = next(r for r in records if r.superseded_commit == PREMATURE_OQ_FREEZE_COMMIT)
    assert freeze["supersession_record_sha256"] == rec.entry_hash
    assert freeze["superseded_freeze_artifact_sha256"] == rec.superseded_freeze_artifact_sha256


def test_freeze_binds_no_wall_clock() -> None:
    # No wall-clock timestamp field (a re-run at a different instant must produce identical bytes).
    # "runtime_contract" is an environment contract, not a clock, so the denylist is timestamp-only.
    freeze = build_oq_source_freeze(REPO)
    for key in freeze:
        assert not any(
            token in key.lower()
            for token in (
                "generated",
                "timestamp",
                "wall_clock",
                "created",
                "built_at",
                "event_time",
            )
        ), key


def test_fingerprint_is_domain_separated_and_digest_binds_whole_body() -> None:
    freeze = build_oq_source_freeze(REPO)
    expected_fingerprint = canonical_sha256(
        {
            "domain": F._FINGERPRINT_DOMAIN,
            "frozen_source_sha256": freeze["frozen_source_sha256"],
            "frozen_artifact_sha256": freeze["frozen_artifact_sha256"],
        }
    )
    assert freeze["source_fingerprint_sha256"] == expected_fingerprint
    # The aggregate digest binds every other field (computed last over the whole body).
    body = {k: v for k, v in freeze.items() if k != "source_freeze_digest"}
    assert freeze["source_freeze_digest"] == canonical_sha256(body)
    # Flipping any single frozen hash changes the fingerprint.
    src = dict(freeze["frozen_source_sha256"])
    src[next(iter(src))] = "0" * 64
    mutated = canonical_sha256(
        {
            "domain": F._FINGERPRINT_DOMAIN,
            "frozen_source_sha256": src,
            "frozen_artifact_sha256": freeze["frozen_artifact_sha256"],
        }
    )
    assert mutated != freeze["source_fingerprint_sha256"]


# --------------------------------------------------------------------------- #
# Scope: the frozen set is exactly the OQ closure (minus shims/self) + extras #
# --------------------------------------------------------------------------- #
def test_frozen_set_equals_oq_closure_minus_exclusions_plus_extras() -> None:
    closure = _oq_execution_closure()
    frozen = set(build_oq_source_freeze(REPO)["frozen_source_sha256"])
    # No stale exclusion: every excluded relpath is genuinely in the live closure.
    assert closure >= _EXCLUSIONS
    # Every deliberate extra is genuinely NOT reached by the OQ runner (an intentional addition).
    assert _DELIBERATE_EXTRAS.isdisjoint(closure)
    # The frozen set is exactly the executed project modules (minus shims/self) plus the extras;
    # a module entering or leaving the OQ closure fails this until frozen or documented.
    assert frozen == (closure - _EXCLUSIONS) | _DELIBERATE_EXTRAS


def test_freeze_covers_the_qualification_defining_source() -> None:
    source = build_oq_source_freeze(REPO)["frozen_source_sha256"]
    for expected in (
        "src/eth_research/v2c/firewall.py",
        "src/eth_research/v2c/oq/events.py",
        "src/eth_research/v2c/oq/slo.py",
        "src/eth_research/v2c/oq/registry.py",
        "src/eth_research/v2c/oq/orchestrator.py",
        "src/eth_research/shadow/runner.py",
        "src/eth_research/v2c/buyer/boundary.py",
        "src/eth_research/v2c/readiness.py",
        "src/eth_research/data/provenance.py",
    ):
        assert expected in source, expected


# --------------------------------------------------------------------------- #
# Fail-closed drift refusals (section 9D)                                     #
# --------------------------------------------------------------------------- #
def test_verify_detects_source_drift(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    verify_oq_source_freeze(tmp_path)  # clean
    victim = tmp_path / "src/eth_research/v2c/firewall.py"
    victim.write_text(victim.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    with pytest.raises(OQSourceFreezeError, match=r"did not reproduce|does not reproduce|changed"):
        verify_oq_source_freeze(tmp_path)


def test_missing_frozen_file_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    (tmp_path / "src/eth_research/v2c/firewall.py").unlink()
    with pytest.raises(OQSourceFreezeError, match="missing"):
        build_oq_source_freeze(tmp_path)


def test_symlinked_frozen_file_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    victim = tmp_path / "src/eth_research/v2c/readiness.py"
    victim.unlink()
    victim.symlink_to(tmp_path / "src/eth_research/v2c/firewall.py")
    with pytest.raises(OQSourceFreezeError, match="symlink"):
        build_oq_source_freeze(tmp_path)


def test_read_bytes_refuses_a_traversal_escape(tmp_path: Path) -> None:
    (tmp_path.parent / "outside.txt").write_text("secret\n", encoding="utf-8")
    with pytest.raises(OQSourceFreezeError, match="escapes the repository root"):
        F._read_bytes(tmp_path, "../outside.txt")


def test_duplicate_relpath_is_rejected() -> None:
    with pytest.raises(OQSourceFreezeError, match="duplicate"):
        F._distinct(("src/a.py", "src/a.py"))


def test_missing_supersession_record_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    (tmp_path / OQ_SUPERSESSION_PATH).unlink()  # no ledger -> premature freeze not recorded
    with pytest.raises(OQSourceFreezeError, match="not recorded superseded"):
        build_oq_source_freeze(tmp_path)


def test_missing_runtime_contract_is_rejected(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    (tmp_path / CANONICAL_RUNTIME_CONTRACT_RELPATH).unlink()
    with pytest.raises(OQSourceFreezeError, match="missing"):
        build_oq_source_freeze(tmp_path)


def test_frozen_source_list_has_no_duplicates() -> None:
    relpaths = F._FROZEN_SOURCE_RELPATHS
    assert len(relpaths) == len(set(relpaths))


# --------------------------------------------------------------------------- #
# OQ-E2A activation anchor (section 9C)                                        #
# --------------------------------------------------------------------------- #
def test_activation_anchor_round_trips_and_binds_the_freeze(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    commit = "b1" * 20
    write_oq_e2_activation(tmp_path, source_freeze_commit=commit)
    verify_oq_e2_activation(tmp_path)  # reproduces from the freeze it names
    activation = build_oq_e2_activation(tmp_path, source_freeze_commit=commit)
    assert activation["source_freeze_commit"] == commit
    assert activation["freeze_id"] == OQ_E2_FREEZE_ID
    assert activation["superseded_freeze_commit"] == PREMATURE_OQ_FREEZE_COMMIT
    freeze_bytes = (tmp_path / OQ_SOURCE_FREEZE_RELPATH).read_bytes()
    assert activation["source_freeze_artifact_sha256"] == sha256_bytes(freeze_bytes)
    assert (
        activation["source_freeze_digest"]
        == build_oq_source_freeze(tmp_path)["source_freeze_digest"]
    )


def test_activation_verify_refuses_tampered_bytes(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    write_oq_e2_activation(tmp_path, source_freeze_commit="a" * 40)
    path = tmp_path / OQ_E2_ACTIVATION_RELPATH
    path.write_bytes(path.read_bytes() + b" ")  # any byte tamper breaks byte-exact reproduction
    with pytest.raises(OQSourceFreezeError, match="does not reproduce"):
        verify_oq_e2_activation(tmp_path)


def test_activation_verify_refuses_a_non_git_sha_commit(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    write_oq_e2_activation(tmp_path, source_freeze_commit="a" * 40)
    path = tmp_path / OQ_E2_ACTIVATION_RELPATH
    obj = json.loads(path.read_bytes())
    obj["source_freeze_commit"] = "not-a-sha"
    path.write_bytes((json.dumps(obj) + "\n").encode("utf-8"))
    with pytest.raises(OQSourceFreezeError, match="40-hex"):
        verify_oq_e2_activation(tmp_path)


def test_activation_detects_freeze_drift(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    write_oq_e2_activation(tmp_path, source_freeze_commit="a" * 40)
    victim = tmp_path / "src/eth_research/v2c/firewall.py"
    victim.write_text(victim.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    with pytest.raises(OQSourceFreezeError):
        verify_oq_e2_activation(tmp_path)


def test_build_activation_refuses_a_bad_commit(tmp_path: Path) -> None:
    _make_fake_repo(tmp_path)
    write_oq_source_freeze(tmp_path)
    with pytest.raises(OQSourceFreezeError, match="40-hex"):
        build_oq_e2_activation(tmp_path, source_freeze_commit="deadbeef")
