"""Frozen research dossier: one complete graph manifest, verified semantically.

Closure E/B5: ``frozen_dossier.json`` (dossier schema v3) is the single
graph file, and :func:`verify_frozen_dossier` checks graph *semantics* —
mutating the train/validation results, the report, the decision (JSON or
Markdown), the discovery chain, or the holdout identity breaks
verification even when the attacker refreshes every anchor hash.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import eth_research
from conftest import GitPipeline
from eth_research.data.acquisition_plan import load_acquisition_receipt
from eth_research.dossier import (
    AUDIT_CANONICAL_CONTENT_MATCH,
    AUDIT_CONTENT_DISCREPANCY,
    AUDIT_NOT_PERFORMED,
    DossierError,
    DossierVerification,
    FrozenResearchDossier,
    IndependentAuditRecord,
    ReacquisitionAudit,
    build_frozen_dossier,
    load_frozen_dossier,
    raw_bundle_fingerprint,
    verify_frozen_dossier,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ANCHOR = REPO_ROOT / "research/m2b/frozen_dossier.json"
ATTEMPT_REL = "research/m2b/raw/coinbase/coinbase-eth-usd-001"
REGISTRATION_COMMIT = "b89627463775bf32698effb5adea1270a5927890"
FROZEN_M2_VERSION = "0.3.0"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ATTEMPT_REL).is_dir(), reason="canonical acquisition not present"
)


def _tamper_json(path: Path, **changes: object) -> None:
    payload = json.loads(path.read_bytes())
    payload.update(changes)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rebuild_dossier(root: Path) -> None:
    """What an attacker does after editing artifacts: refresh every anchor."""
    anchor = root / "research/m2b/frozen_dossier.json"
    anchor.write_bytes(build_frozen_dossier(root).to_json_bytes())


def _verify(gp: GitPipeline) -> DossierVerification:
    return verify_frozen_dossier(
        gp.repo_root,
        manifest_path=gp.manifest_path,
        raw_chunk_dir=gp.raw_chunk_dir,
        derived_csv=gp.derived_csv,
    )


class TestFrozenSnapshotVerification:
    """The committed 0.3.0 dossier verifies as a frozen snapshot at any
    running package version (e.g. Milestone 3A at 0.4.0), and tampering a
    frozen data artifact is still caught in that mode."""

    def test_real_repo_verifies_in_snapshot_mode_when_version_advanced(self) -> None:
        import eth_research
        from eth_research.replay_m2b import reconstruct_dataset

        if eth_research.__version__ == FROZEN_M2_VERSION:
            pytest.skip("running the frozen version exercises live mode, not snapshot mode")
        import tempfile

        work = Path(tempfile.mkdtemp())
        res = reconstruct_dataset(REPO_ROOT, "coinbase-eth-usd-001", work)
        result = verify_frozen_dossier(
            REPO_ROOT,
            manifest_path=res.build.manifest_path,
            raw_chunk_dir=REPO_ROOT / ATTEMPT_REL,
            derived_csv=res.derived_csv,
        )
        assert result.ok, result.errors
        assert "snapshot_mode" in result.checks
        # Data-integrity anchors and the byte-exact evidence regeneration
        # still run in snapshot mode.
        assert "holdout:committed_bytes" in result.checks
        assert "evidence:results_bytes" in result.checks


class TestCommittedDossier:
    """The real repository's committed manifest."""

    def test_round_trips_byte_stably(self) -> None:
        dossier = load_frozen_dossier(ANCHOR)
        assert dossier.to_json_bytes() == ANCHOR.read_bytes()

    def test_pins_the_protocol_registration_commit(self) -> None:
        dossier = load_frozen_dossier(ANCHOR)
        assert dossier.protocol_registration_commit_sha == REGISTRATION_COMMIT
        assert dossier.selected_attempt_id == "coinbase-eth-usd-001"
        # The dossier records the package version that froze it (Milestone
        # 2B → 0.3.0), which is not necessarily the running version once a
        # later milestone (3A) advances the package.
        assert dossier.package_version == FROZEN_M2_VERSION

    def test_audit_status_is_explicit_never_absent(self) -> None:
        audit = load_frozen_dossier(ANCHOR).independent_audit
        assert audit.status in (AUDIT_NOT_PERFORMED, AUDIT_CANONICAL_CONTENT_MATCH)
        if audit.status == AUDIT_NOT_PERFORMED:
            assert audit.reason is not None
            assert "GitHub Actions" in audit.reason
        else:
            assert audit.reacquisition_audit_sha256 is not None

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(ANCHOR.read_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            FrozenResearchDossier.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_invalid_file_raises_dossier_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "frozen_dossier.json"
        bad.write_bytes(b"{}")
        with pytest.raises(DossierError, match="invalid frozen dossier"):
            load_frozen_dossier(bad)


@pytest.fixture
def cloned_root(tmp_path: Path) -> Path:
    """A tamperable copy of the committed dossier tree (anchor-stage tests)."""
    shutil.copytree(REPO_ROOT / "research", tmp_path / "research")
    shutil.copy(REPO_ROOT / "uv.lock", tmp_path / "uv.lock")
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def _verify_clone(root: Path) -> DossierVerification:
    # Anchor-stage failures return before the dataset arguments are touched.
    return verify_frozen_dossier(
        root,
        manifest_path=root / "research/m2b/dataset_manifest.json",
        raw_chunk_dir=root / ATTEMPT_REL,
        derived_csv=root / "unused-derived.csv",
    )


class TestAnchorsCatchTampering:
    """Without a refreshed dossier, any artifact edit dies at its anchor."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("workflow_run_id", "00000000000"),
            ("source_commit", "0" * 40),
            ("curl_version", "curl 9.9.9"),
            ("runner", "attacker-laptop"),
        ],
    )
    def test_forged_receipt_metadata_breaks_the_anchor(
        self, cloned_root: Path, field: str, value: str
    ) -> None:
        _tamper_json(cloned_root / ATTEMPT_REL / "acquisition_receipt.json", **{field: value})
        result = _verify_clone(cloned_root)
        assert not result.ok
        assert any("acquisition_receipt_sha256" in error for error in result.errors)

    @pytest.mark.parametrize(
        ("relpath", "expected"),
        [
            ("research/m2b/train_validation_results.json", "train_validation_results_sha256"),
            ("research/m2b/validation_decision.json", "validation_decision_sha256"),
            ("research/m2b/holdout_identity.json", "holdout_identity_sha256"),
            ("research/m2b/discovery_decision.json", "discovery_decision_sha256"),
        ],
    )
    def test_edited_artifact_breaks_its_anchor(
        self, cloned_root: Path, relpath: str, expected: str
    ) -> None:
        path = cloned_root / relpath
        path.write_bytes(path.read_bytes() + b"\n")
        result = _verify_clone(cloned_root)
        assert not result.ok
        assert any(expected in error for error in result.errors)

    def test_edited_markdown_breaks_its_anchor(self, cloned_root: Path) -> None:
        path = cloned_root / "research/m2b/validation_decision.md"
        path.write_text(path.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
        result = _verify_clone(cloned_root)
        assert not result.ok
        assert any("validation_decision_markdown_sha256" in error for error in result.errors)

    def test_forged_byte_length_is_caught_by_the_raw_bundle(self, cloned_root: Path) -> None:
        receipt_path = cloned_root / ATTEMPT_REL / "acquisition_receipt.json"
        payload = json.loads(receipt_path.read_bytes())
        payload["responses"][0]["byte_length"] = payload["responses"][0]["byte_length"] + 1
        receipt_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt = load_acquisition_receipt(receipt_path)
        with pytest.raises(DossierError, match="byte_length"):
            raw_bundle_fingerprint(receipt, cloned_root / ATTEMPT_REL)

    def test_raw_bundle_fingerprint_is_deterministic(self) -> None:
        receipt = load_acquisition_receipt(REPO_ROOT / ATTEMPT_REL / "acquisition_receipt.json")
        first = raw_bundle_fingerprint(receipt, REPO_ROOT / ATTEMPT_REL)
        second = raw_bundle_fingerprint(receipt, REPO_ROOT / ATTEMPT_REL)
        assert first == second
        assert first.startswith("sha256:")


class TestGraphSemantics:
    """B5: refreshing every anchor hash is not enough — the graph re-derives."""

    def test_untampered_fixture_verifies_completely(self, git_pipeline: GitPipeline) -> None:
        result = _verify(git_pipeline)
        assert result.ok, result.errors
        assert len(result.checks) >= 40
        required = {
            "discovery:decision",
            "dataset:lock_evidence_semantic",
            "dataset:reload_fingerprint_protocol",
            "holdout:recompute",
            "holdout:committed_bytes",
            "evidence:registration",
            "evidence:registration_history",
            "evidence:regenerate",
            "evidence:results_bytes",
            "evidence:report_bytes",
            "evidence:decision_bytes",
            "evidence:decision_markdown",
            "version_chain",
        }
        assert required.issubset(set(result.checks))
        assert any(check.startswith("audit:explicitly_not_performed") for check in result.checks)
        result.raise_for_status()  # must not raise on a healthy dossier
        assert result.decision is not None
        assert result.protocol_registration_commit_sha == git_pipeline.registration_head

    def test_edited_return_number_dies_at_the_strict_parse(self, git_pipeline: GitPipeline) -> None:
        # Layer 1: an edited return breaks the reconstructable accounting
        # identities, so the committed results no longer even parse.
        gp = git_pipeline
        results = gp.repo_root / "research/m2b/train_validation_results.json"
        payload = json.loads(results.read_bytes())
        payload["segments"][0]["total_return"] = payload["segments"][0]["total_return"] + 0.5
        results.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:registration" in error for error in result.errors)
        assert any("total_return" in error for error in result.errors)

    def test_parseable_results_drift_fails_regeneration_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        # Layer 2: a parseable edit (no identity broken) still cannot
        # regenerate byte-for-byte from the verified dataset.
        gp = git_pipeline
        results = gp.repo_root / "research/m2b/train_validation_results.json"
        _tamper_json(results, package_version="9.9.9")
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:results_bytes" in error for error in result.errors)

    def test_relabelled_registration_commit_is_refused_by_history(
        self, git_pipeline: GitPipeline
    ) -> None:
        # B6/relabelling: point the stored registration at another *real*
        # commit and hand-edit the dossier to agree — git history refuses.
        gp = git_pipeline
        assert gp.head != gp.registration_head
        _tamper_json(
            gp.repo_root / "research/m2b/train_validation_results.json",
            protocol_registration_commit_sha=gp.head,
        )
        _tamper_json(
            gp.repo_root / "research/m2b/frozen_dossier.json",
            protocol_registration_commit_sha=gp.head,
        )
        _tamper_json(
            gp.repo_root / "research/m2b/frozen_dossier.json",
            train_validation_results_sha256=hashlib.sha256(
                (gp.repo_root / "research/m2b/train_validation_results.json").read_bytes()
            ).hexdigest(),
        )
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:registration_history" in error for error in result.errors)
        assert any("relabelled registration cannot verify" in error for error in result.errors)

    def test_edited_report_fails_regeneration_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        gp = git_pipeline
        report = gp.repo_root / "research/m2b/train_validation_report.md"
        report.write_text(
            report.read_text(encoding="utf-8").replace("ETH benchmark report", "Great results"),
            encoding="utf-8",
        )
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:report_bytes" in error for error in result.errors)

    def test_edited_decision_json_fails_rebuild_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        gp = git_pipeline
        decision = gp.repo_root / "research/m2b/validation_decision.json"
        raw = decision.read_bytes()
        decision.write_bytes(raw.replace(b"underperform", b"outperform"))
        assert decision.read_bytes() != raw
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:decision_bytes" in error for error in result.errors)

    def test_edited_decision_markdown_fails_rerender_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        gp = git_pipeline
        md = gp.repo_root / "research/m2b/validation_decision.md"
        md.write_text(md.read_text(encoding="utf-8") + "\nLooks great.\n", encoding="utf-8")
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("evidence:decision_markdown" in error for error in result.errors)

    def test_edited_discovery_decision_fails_raw_reverify_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        gp = git_pipeline
        _tamper_json(
            gp.repo_root / "research/m2b/discovery_decision.json",
            discovery_candle_count=29,
        )
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("discovery:decision" in error for error in result.errors)

    def test_forged_holdout_identity_fails_recompute_despite_fresh_anchors(
        self, git_pipeline: GitPipeline
    ) -> None:
        gp = git_pipeline
        _tamper_json(
            gp.repo_root / "research/m2b/holdout_identity.json",
            test_content_fingerprint="sha256:" + "f" * 64,
        )
        _rebuild_dossier(gp.repo_root)
        result = _verify(gp)
        assert not result.ok
        assert any("holdout:committed_bytes" in error for error in result.errors)

    def test_claimed_audit_without_the_audit_artifact_fails(
        self, git_pipeline: GitPipeline
    ) -> None:
        # An attacker writes a dossier claiming a performed, matching audit
        # but commits no reacquisition record: the audit chain must fail.
        gp = git_pipeline
        fabricated = IndependentAuditRecord(
            status=AUDIT_CANONICAL_CONTENT_MATCH,
            reason=None,
            audit_attempt_id="coinbase-eth-usd-audit-002",
            audit_request_plan_sha256="1" * 64,
            audit_receipt_sha256="2" * 64,
            audit_raw_bundle_fingerprint="sha256:" + "3" * 64,
            reacquisition_audit_sha256="4" * 64,
        )
        dossier = build_frozen_dossier(gp.repo_root, independent_audit=fabricated)
        (gp.repo_root / "research/m2b/frozen_dossier.json").write_bytes(dossier.to_json_bytes())
        result = _verify(gp)
        assert not result.ok
        assert any("audit:" in error for error in result.errors)


def make_reacquisition(**overrides: Any) -> ReacquisitionAudit:
    fields: dict[str, Any] = {
        "reacquisition_schema_version": 1,
        "original_attempt_id": "coinbase-eth-usd-001",
        "audit_attempt_id": "coinbase-eth-usd-audit-002",
        "workflow_run_id": "12345678901",
        "source_commit": "a" * 40,
        "original_request_plan_sha256": "1" * 64,
        "audit_request_plan_sha256": "1" * 64,
        "original_receipt_sha256": "2" * 64,
        "audit_receipt_sha256": "3" * 64,
        "original_raw_bundle_fingerprint": "sha256:" + "4" * 64,
        "audit_raw_bundle_fingerprint": "sha256:" + "5" * 64,
        "original_derived_csv_sha256": "6" * 64,
        "audit_derived_csv_sha256": "6" * 64,
        "original_content_fingerprint": "sha256:" + "7" * 64,
        "audit_content_fingerprint": "sha256:" + "7" * 64,
        "original_row_count": 3702,
        "audit_row_count": 3702,
        "original_first_open_time": "2016-05-23T00:00:00+00:00",
        "original_last_open_time": "2026-07-11T00:00:00+00:00",
        "audit_first_open_time": "2016-05-23T00:00:00+00:00",
        "audit_last_open_time": "2026-07-11T00:00:00+00:00",
        "comparison_status": AUDIT_CANONICAL_CONTENT_MATCH,
        "differing_candle_count": 0,
        "canonical_data_replaced": False,
    }
    fields.update(overrides)
    return ReacquisitionAudit(**fields)


class TestReacquisitionAuditModel:
    """The strict comparison record for the independent reacquisition (H)."""

    def test_round_trips_byte_stably(self) -> None:
        record = make_reacquisition()
        assert ReacquisitionAudit.from_json_bytes(record.to_json_bytes()) == record

    def test_replacing_canonical_data_is_never_recordable(self) -> None:
        with pytest.raises(ValueError, match="never replaces frozen data"):
            make_reacquisition(canonical_data_replaced=True)

    def test_comparison_status_is_an_enum_not_free_text(self) -> None:
        with pytest.raises(ValueError, match="comparison enum"):
            make_reacquisition(comparison_status="looks fine")
        with pytest.raises(ValueError, match="comparison enum"):
            make_reacquisition(comparison_status=AUDIT_NOT_PERFORMED)

    def test_match_requires_equal_content(self) -> None:
        with pytest.raises(ValueError, match="equal content fingerprints"):
            make_reacquisition(audit_content_fingerprint="sha256:" + "8" * 64)
        with pytest.raises(ValueError, match="equal derived CSV bytes"):
            make_reacquisition(audit_derived_csv_sha256="9" * 64)
        with pytest.raises(ValueError, match="equal row counts"):
            make_reacquisition(audit_row_count=3701)
        with pytest.raises(ValueError, match="zero differing candles"):
            make_reacquisition(differing_candle_count=3)

    def test_discrepancy_requires_a_differing_candle_count(self) -> None:
        with pytest.raises(ValueError, match="at least one differing candle"):
            make_reacquisition(
                comparison_status=AUDIT_CONTENT_DISCREPANCY, differing_candle_count=0
            )

    def test_audit_attempt_must_be_distinct(self) -> None:
        with pytest.raises(ValueError, match="distinct from the original"):
            make_reacquisition(audit_attempt_id="coinbase-eth-usd-001")

    def test_audit_must_fulfil_the_unchanged_plan(self) -> None:
        with pytest.raises(ValueError, match="unchanged canonical request plan"):
            make_reacquisition(audit_request_plan_sha256="f" * 64)

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(make_reacquisition().to_json_bytes())
        payload["note"] = "extra"
        with pytest.raises(ValueError, match=r"unknown=\['note'\]"):
            ReacquisitionAudit.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestIndependentAuditRecordModel:
    def test_not_performed_requires_a_reason_and_null_chain(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            IndependentAuditRecord(
                status=AUDIT_NOT_PERFORMED,
                reason=None,
                audit_attempt_id=None,
                audit_request_plan_sha256=None,
                audit_receipt_sha256=None,
                audit_raw_bundle_fingerprint=None,
                reacquisition_audit_sha256=None,
            )
        with pytest.raises(ValueError, match="must be null when not performed"):
            IndependentAuditRecord(
                status=AUDIT_NOT_PERFORMED,
                reason="pending",
                audit_attempt_id="coinbase-eth-usd-audit-002",
                audit_request_plan_sha256=None,
                audit_receipt_sha256=None,
                audit_raw_bundle_fingerprint=None,
                reacquisition_audit_sha256=None,
            )

    def test_performed_requires_the_full_chain_and_no_reason(self) -> None:
        with pytest.raises(ValueError, match="reason must be null when performed"):
            IndependentAuditRecord(
                status=AUDIT_CANONICAL_CONTENT_MATCH,
                reason="done",
                audit_attempt_id="coinbase-eth-usd-audit-002",
                audit_request_plan_sha256="1" * 64,
                audit_receipt_sha256="2" * 64,
                audit_raw_bundle_fingerprint="sha256:" + "3" * 64,
                reacquisition_audit_sha256="4" * 64,
            )
        with pytest.raises(ValueError, match="audit_receipt_sha256"):
            IndependentAuditRecord(
                status=AUDIT_CANONICAL_CONTENT_MATCH,
                reason=None,
                audit_attempt_id="coinbase-eth-usd-audit-002",
                audit_request_plan_sha256="1" * 64,
                audit_receipt_sha256=None,
                audit_raw_bundle_fingerprint="sha256:" + "3" * 64,
                reacquisition_audit_sha256="4" * 64,
            )

    def test_unknown_status_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            IndependentAuditRecord(
                status="skipped",
                reason="whatever",
                audit_attempt_id=None,
                audit_request_plan_sha256=None,
                audit_receipt_sha256=None,
                audit_raw_bundle_fingerprint=None,
                reacquisition_audit_sha256=None,
            )

    def test_unknown_key_is_rejected(self) -> None:
        payload = load_frozen_dossier(ANCHOR).independent_audit.to_json_dict()
        payload["note"] = "extra"
        with pytest.raises(ValueError, match="do not match schema"):
            IndependentAuditRecord.from_json_dict(payload)
