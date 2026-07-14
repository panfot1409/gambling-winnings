"""Adversarial tests for the append-only artifact-errata layer.

Three surfaces are attacked: the strict :class:`ArtifactErratum` /
:class:`AffectedCell` models, the hash-chained errata registry, and the
end-to-end :func:`verify_artifact_errata` against a disposable copy of the real
research tree. Every mutation must be rejected, and no test may cause a sealed
ledger to gain a byte.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.artifact_errata import (
    ArtifactErrataError,
    ArtifactErratum,
    ErrataRegistryEntry,
    build_report_zero_inclusion_erratum,
    interval_contains_zero,
    read_errata_registry,
    render_erratum_markdown,
    statement_domain_sha256,
    verify_artifact_errata,
)
from eth_research.data.provenance import sha256_bytes

REPO = Path(eth_research.__file__).resolve().parents[2]
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"
_ERRATA_REGISTRY = "research/m3a/artifact_errata.jsonl"
_ERRATUM_JSON = "research/m3a/errata/m3a-run003-report-zero-inclusion-v1.json"
_ERRATUM_MD = "research/m3a/errata/m3a-run003-report-zero-inclusion-v1.md"
_RUN003 = "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003"


def _make_errata_repo(tmp_path: Path) -> Path:
    """A disposable copy of the committed research tree that verifies as-is."""
    root = tmp_path / "repo"
    (root / "research/m3a").mkdir(parents=True)
    (root / "research/m2b").mkdir(parents=True)
    shutil.copy(REPO / "research/m3a/experiment_registry.jsonl", root / "research/m3a")
    shutil.copytree(REPO / "research/m3a/experiments", root / "research/m3a/experiments")
    shutil.copytree(REPO / "research/m3a/errata", root / "research/m3a/errata")
    shutil.copy(REPO / _ERRATA_REGISTRY, root / _ERRATA_REGISTRY)
    (root / _GATE_LEDGER).write_bytes(b"")
    (root / _HOLDOUT_LEDGER).write_bytes(b"")
    return root


def _assert_ledgers_empty(root: Path) -> None:
    assert (root / _GATE_LEDGER).read_bytes() == b""
    assert (root / _HOLDOUT_LEDGER).read_bytes() == b""


def _valid_erratum() -> ArtifactErratum:
    return build_report_zero_inclusion_erratum(REPO)


def _erratum_dict() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((REPO / _ERRATUM_JSON).read_bytes())
    return data


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def test_committed_errata_verify_and_leave_ledgers_empty() -> None:
    ids = verify_artifact_errata(REPO)
    assert ids == ("m3a-run003-report-zero-inclusion-v1",)


def test_interval_contains_zero_full_precision() -> None:
    assert interval_contains_zero(-1.0, 1.0)
    assert interval_contains_zero(0.0, 0.0)
    assert not interval_contains_zero(-5e-3, -1e-5)  # cash primary: excludes zero
    assert not interval_contains_zero(1e-9, 2e-9)
    with pytest.raises(ValueError, match="exceeds"):
        interval_contains_zero(1.0, -1.0)  # inverted


def test_disposable_repo_verifies() -> None:
    root = _make_errata_repo_via_tmp()
    assert verify_artifact_errata(root) == ("m3a-run003-report-zero-inclusion-v1",)
    _assert_ledgers_empty(root)


_TMP_HOLDER: list[Path] = []


def _make_errata_repo_via_tmp() -> Path:
    import tempfile

    d = Path(tempfile.mkdtemp())
    _TMP_HOLDER.append(d)
    return _make_errata_repo(d)


# --------------------------------------------------------------------------- #
# Model-level: AffectedCell
# --------------------------------------------------------------------------- #
class TestAffectedCellModel:
    def test_zero_included_must_agree_with_bounds(self) -> None:
        from eth_research.artifact_errata import AffectedCell

        with pytest.raises(ValueError, match="inconsistent"):
            AffectedCell("cash", "base", "primary", -5e-3, -1e-5, zero_included=True)

    def test_inverted_bounds_rejected(self) -> None:
        from eth_research.artifact_errata import AffectedCell

        with pytest.raises(ValueError, match="exceeds"):
            AffectedCell("cash", "base", "primary", 1.0, -1.0, zero_included=False)

    def test_ci_upper_exactly_zero_is_contained(self) -> None:
        from eth_research.artifact_errata import AffectedCell

        # ci_upper == 0 means zero IS included; claiming it excludes zero fails.
        with pytest.raises(ValueError, match="inconsistent"):
            AffectedCell("cash", "base", "primary", -5e-3, 0.0, zero_included=False)

    def test_bounds_must_be_float_not_int(self) -> None:
        from eth_research.artifact_errata import AffectedCell

        with pytest.raises(ValueError, match="must be a float"):
            # int where a float is required: rejected at runtime by _require_float.
            AffectedCell("cash", "base", "primary", 0, 1.0, zero_included=True)

    def test_unknown_interval_kind_rejected(self) -> None:
        from eth_research.artifact_errata import AffectedCell

        with pytest.raises(ValueError, match="interval_kind"):
            AffectedCell("cash", "base", "tertiary", -5e-3, -1e-5, zero_included=False)


# --------------------------------------------------------------------------- #
# Model-level: ArtifactErratum JSON
# --------------------------------------------------------------------------- #
class TestErratumModel:
    def test_roundtrip_is_canonical(self) -> None:
        er = _valid_erratum()
        raw = er.to_canonical_bytes()
        assert ArtifactErratum.from_json_bytes(raw).to_canonical_bytes() == raw

    def test_unknown_key_rejected(self) -> None:
        d = _erratum_dict()
        d["extra"] = 1
        with pytest.raises(ValueError, match="keys do not match"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_missing_key_rejected(self) -> None:
        d = _erratum_dict()
        del d["corrected_statement"]
        with pytest.raises(ValueError, match="keys do not match"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_duplicate_top_level_key_rejected(self) -> None:
        raw = (REPO / _ERRATUM_JSON).read_text()
        dup = raw.rstrip().rstrip("}") + ',"erratum_id":"x"}'
        with pytest.raises(ValueError, match="duplicate"):
            ArtifactErratum.from_json_bytes(dup.encode())

    def test_nan_rejected(self) -> None:
        raw = (REPO / _ERRATUM_JSON).read_text().replace("-0.005063937422795938", "NaN")
        with pytest.raises(ValueError, match="not valid JSON"):
            ArtifactErratum.from_json_bytes(raw.encode())

    def test_infinity_rejected(self) -> None:
        raw = (REPO / _ERRATUM_JSON).read_text().replace("-0.005063937422795938", "Infinity")
        with pytest.raises(ValueError, match="not valid JSON"):
            ArtifactErratum.from_json_bytes(raw.encode())

    def test_overflow_exponent_rejected(self) -> None:
        raw = (REPO / _ERRATUM_JSON).read_text().replace("-0.005063937422795938", "1e999")
        with pytest.raises(ValueError, match="not valid JSON"):
            ArtifactErratum.from_json_bytes(raw.encode())

    def test_bool_as_int_schema_version_rejected(self) -> None:
        d = _erratum_dict()
        d["errata_schema_version"] = True
        with pytest.raises(ValueError, match="integer"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_claiming_financial_values_changed_rejected(self) -> None:
        d = _erratum_dict()
        d["financial_values_changed"] = True
        with pytest.raises(ValueError, match="must be false"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_claiming_gate_access_rejected(self) -> None:
        d = _erratum_dict()
        d["development_gate_accessed"] = True
        with pytest.raises(ValueError, match="must be false"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_claiming_holdout_access_rejected(self) -> None:
        d = _erratum_dict()
        d["final_holdout_accessed"] = True
        with pytest.raises(ValueError, match="must be false"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_statement_hash_must_match_statement(self) -> None:
        d = _erratum_dict()
        d["erroneous_statement"] = "a different (wrong) statement entirely"
        with pytest.raises(ValueError, match="statement_sha256"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_affected_strategies_must_match_cells(self) -> None:
        d = _erratum_dict()
        d["affected_strategies"] = ["cash", "sma_20_50"]
        with pytest.raises(ValueError, match="affected_strategies"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_unsafe_target_path_rejected(self) -> None:
        d = _erratum_dict()
        d["target_artifact_relpath"] = "research/m3a/../../etc/passwd"
        with pytest.raises(ValueError, match="dot components"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())

    def test_target_path_outside_m3a_rejected(self) -> None:
        d = _erratum_dict()
        d["target_artifact_relpath"] = "research/m2b/something.md"
        with pytest.raises(ValueError, match="must live under"):
            ArtifactErratum.from_json_bytes(json.dumps(d).encode())


# --------------------------------------------------------------------------- #
# Registry-level: chain + single-use ids
# --------------------------------------------------------------------------- #
class TestErrataRegistryChain:
    def test_reads_the_committed_registry(self) -> None:
        entries = read_errata_registry(REPO / _ERRATA_REGISTRY)
        assert [e.erratum_id for e in entries] == ["m3a-run003-report-zero-inclusion-v1"]

    def test_missing_trailing_newline_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "reg.jsonl"
        p.write_bytes((REPO / _ERRATA_REGISTRY).read_bytes().rstrip(b"\n"))
        with pytest.raises(ArtifactErrataError, match="newline"):
            read_errata_registry(p)

    def test_broken_previous_hash_rejected(self, tmp_path: Path) -> None:
        line = (REPO / _ERRATA_REGISTRY).read_bytes().rstrip(b"\n")
        d = json.loads(line)
        d["previous_entry_sha256"] = "1" * 64
        p = tmp_path / "reg.jsonl"
        p.write_bytes(ErrataRegistryEntry.from_json_line(json.dumps(d).encode()).to_json_line())
        with pytest.raises(ArtifactErrataError, match="previous_entry_sha256"):
            read_errata_registry(p)

    def test_duplicate_erratum_id_rejected(self, tmp_path: Path) -> None:
        entries = read_errata_registry(REPO / _ERRATA_REGISTRY)
        first = entries[0]
        line1 = first.to_json_line()
        second = ErrataRegistryEntry(
            errata_schema_version=first.errata_schema_version,
            erratum_id=first.erratum_id,  # duplicate id
            erratum_relpath=first.erratum_relpath,
            erratum_sha256=first.erratum_sha256,
            erratum_markdown_relpath=first.erratum_markdown_relpath,
            erratum_markdown_sha256=first.erratum_markdown_sha256,
            target_experiment_id=first.target_experiment_id,
            target_artifact_relpath=first.target_artifact_relpath,
            target_artifact_sha256=first.target_artifact_sha256,
            previous_entry_sha256=sha256_bytes(line1),
        )
        p = tmp_path / "reg.jsonl"
        p.write_bytes(line1 + second.to_json_line())
        with pytest.raises(ArtifactErrataError, match="duplicate erratum id"):
            read_errata_registry(p)

    def test_blank_line_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "reg.jsonl"
        p.write_bytes(b"\n" + (REPO / _ERRATA_REGISTRY).read_bytes())
        with pytest.raises(ArtifactErrataError):
            read_errata_registry(p)


# --------------------------------------------------------------------------- #
# verify_artifact_errata against a disposable repo
# --------------------------------------------------------------------------- #
class TestVerifyAgainstDisposableRepo:
    def test_changed_target_report_byte_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        target = root / f"{_RUN003}/development_report.md"
        target.write_bytes(target.read_bytes() + b"tamper\n")
        with pytest.raises(ArtifactErrataError):
            verify_artifact_errata(root)
        _assert_ledgers_empty(root)

    def test_erroneous_statement_absent_from_target_rejected(self, tmp_path: Path) -> None:
        # If the target report no longer contains the statement, but its hash is
        # updated to match, the completed-event binding must still reject it.
        root = _make_errata_repo(tmp_path)
        target = root / f"{_RUN003}/development_report.md"
        text = target.read_bytes().replace(
            b"every fold-aware bootstrap interval", b"EVERY FOLD-AWARE bootstrap interval"
        )
        target.write_bytes(text)
        with pytest.raises(ArtifactErrataError):
            verify_artifact_errata(root)

    def test_edited_markdown_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        md = root / _ERRATUM_MD
        md.write_bytes(md.read_bytes() + b"\nextra line\n")
        with pytest.raises(ArtifactErrataError, match="markdown"):
            verify_artifact_errata(root)

    def test_erratum_with_fabricated_cell_rejected(self, tmp_path: Path) -> None:
        # Rebuild the erratum with an extra (fabricated) affected cell that is not
        # in the committed results, re-chain the registry, and expect rejection.
        root = _make_errata_repo(tmp_path)
        d = _erratum_dict()
        d["affected_cells"].append(
            {
                "strategy": "sma_20_50",
                "cost_scenario": "base",
                "interval_kind": "primary",
                "ci_lower": -0.01,
                "ci_upper": -0.001,
                "zero_included": False,
            }
        )
        d["affected_strategies"] = ["cash", "sma_20_50"]
        _rewrite_erratum(root, d)
        with pytest.raises(ArtifactErrataError):
            verify_artifact_errata(root)
        _assert_ledgers_empty(root)

    def test_sign_flipped_bound_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        d = _erratum_dict()
        # Flip a cash upper bound positive so the interval now 'contains zero'
        # (zero_included must flip too to stay internally consistent). The cell no
        # longer matches the committed results -> verify must reject it.
        d["affected_cells"][0]["ci_upper"] = 1.220168774754618e-05
        d["affected_cells"][0]["zero_included"] = True
        _rewrite_erratum(root, d)
        with pytest.raises(ArtifactErrataError):
            verify_artifact_errata(root)
        _assert_ledgers_empty(root)

    def test_omitting_one_cash_scenario_rejected(self, tmp_path: Path) -> None:
        # Dropping one zero-excluding cash cell leaves the affected set incomplete;
        # the completeness invariant (affected cells == exactly the zero-excluding
        # intervals) rejects it.
        root = _make_errata_repo(tmp_path)
        d = _erratum_dict()
        d["affected_cells"] = d["affected_cells"][:2]  # drop the 'severe' cell
        d["affected_cost_scenarios"] = ["base", "stressed"]
        _rewrite_erratum(root, d)
        with pytest.raises(ArtifactErrataError, match="not exactly the zero-excluding"):
            verify_artifact_errata(root)
        _assert_ledgers_empty(root)

    def test_symlinked_erratum_path_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        target = root / _ERRATUM_JSON
        payload = target.read_bytes()
        outside = tmp_path / "outside.json"
        outside.write_bytes(payload)
        target.unlink()
        target.symlink_to(outside)
        with pytest.raises(ArtifactErrataError, match="symlink"):
            verify_artifact_errata(root)

    def test_orphan_errata_file_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        (root / "research/m3a/errata/rogue.json").write_bytes(b"{}\n")
        with pytest.raises(ArtifactErrataError, match="orphan"):
            verify_artifact_errata(root)

    def test_gate_ledger_nonempty_rejected(self, tmp_path: Path) -> None:
        root = _make_errata_repo(tmp_path)
        (root / _GATE_LEDGER).write_bytes(b"{}\n")
        with pytest.raises(ArtifactErrataError, match="byte-empty"):
            verify_artifact_errata(root)


def _rewrite_erratum(root: Path, erratum_dict: dict[str, Any]) -> None:
    """Write a mutated erratum JSON + matching Markdown + re-chained registry line."""
    er = ArtifactErratum.from_json_bytes(json.dumps(erratum_dict).encode())
    json_bytes = er.to_canonical_bytes()
    md_bytes = render_erratum_markdown(er)
    (root / _ERRATUM_JSON).write_bytes(json_bytes)
    (root / _ERRATUM_MD).write_bytes(md_bytes)
    entry = ErrataRegistryEntry(
        errata_schema_version=1,
        erratum_id=er.erratum_id,
        erratum_relpath=_ERRATUM_JSON,
        erratum_sha256=sha256_bytes(json_bytes),
        erratum_markdown_relpath=_ERRATUM_MD,
        erratum_markdown_sha256=sha256_bytes(md_bytes),
        target_experiment_id=er.target_experiment_id,
        target_artifact_relpath=er.target_artifact_relpath,
        target_artifact_sha256=er.target_artifact_sha256,
        previous_entry_sha256="0" * 64,
    )
    (root / _ERRATA_REGISTRY).write_bytes(entry.to_json_line())


def test_statement_domain_hash_is_domain_separated() -> None:
    # A domain-separated hash differs from a bare SHA-256 of the same bytes.
    s = (
        "every fold-aware bootstrap interval of mean daily paired excess return "
        "versus buy-and-hold straddles zero"
    )
    assert statement_domain_sha256(s) != sha256_bytes(s.encode("utf-8"))
