"""Section 19 — post-run adversarial verification of the committed run-003.

Once run-003 is published these are the standing proofs that its committed
artifacts are what they claim, and that the immutability guarantees are not
hollow:

* the corrective v2 run is financially **bit-identical** to run-002 (only the
  bootstrap interval resampling and the governance/provenance fields differ);
* the v2 replay **rejects** any single-byte tamper of the compatibility aliases
  or of the immutable per-experiment archive;
* the frozen six-line v1 registry prefix is byte-unchanged; and
* both sealed access ledgers are still byte-empty.

These run unconditionally on every platform — they read committed bytes and
tamper inside a disposable ``git clone --local`` (which hard-links objects and
needs no network), so there is no real-data or frozen-runtime dependency.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research.data.provenance import sha256_bytes
from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH
from eth_research.financial_equivalence import assert_financial_equivalence
from eth_research.replay_m3a_v2 import ReplayV2Error, verify_v2_replay

REPO = Path(eth_research.__file__).resolve().parents[2]
RUN003_ID = "m3a-fixed-baseline-comparison-v2-run-003"
RUN002_RESULTS = (
    REPO
    / "research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-002/development_results.json"
)
RUN003_DIR = REPO / "research/m3a/experiments" / RUN003_ID
RUN003_ARCHIVE_RESULTS = RUN003_DIR / "development_results.json"
RUN003_ARCHIVE_REPORT = RUN003_DIR / "development_report.md"
RESULTS_ALIAS = REPO / "research/m3a/development_results.json"
REPORT_ALIAS = REPO / "research/m3a/development_report.md"
GATE_LEDGER = REPO / "research/m3a/development_gate_access.jsonl"
HOLDOUT_LEDGER = REPO / "research/m2b/test_evaluations.jsonl"

EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
# The frozen v1 registry prefix (run-001 registered/started/completed +
# run-002 registered/started/completed); run-003 may only append after it.
REGISTRY_PREFIX_SHA256 = "7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67"


def _tampered_clone(tmp_path: Path, relpath: str, mutate: Callable[[bytes], bytes]) -> Path:
    """A disposable local clone of the repo with one working-tree file mutated.

    ``git clone --local`` hard-links the object store (fast, no network) and
    checks out HEAD, so the run-003 artifacts and the commits recorded inside
    them are both present; the v2 replay resolves those commits from the clone.
    """
    dest = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--local", "--quiet", str(REPO), str(dest)],
        check=True,
        capture_output=True,
    )
    target = dest / relpath
    target.write_bytes(mutate(target.read_bytes()))
    return dest


class TestCommittedRun003FinancialEquivalence:
    """The headline proof: the committed corrective run changed no financials."""

    def test_run003_archive_is_financially_identical_to_run002(self) -> None:
        summary = assert_financial_equivalence(RUN002_RESULTS, RUN003_ARCHIVE_RESULTS)
        assert summary.fold_cells == 60
        assert summary.independent_fold_summaries == 12
        assert summary.pooled_reset_oos == 12
        assert summary.full_train_exploratory == 12

    def test_alias_mirrors_the_immutable_archive_byte_for_byte(self) -> None:
        assert RESULTS_ALIAS.read_bytes() == RUN003_ARCHIVE_RESULTS.read_bytes()
        assert REPORT_ALIAS.read_bytes() == RUN003_ARCHIVE_REPORT.read_bytes()


class TestV2ReplayRejectsTampering:
    """verify_v2_replay regenerates the v2 artifacts from committed raw bytes and
    byte-compares; a single appended byte anywhere must fail the reproduction."""

    def test_clean_repo_reproduces_run003(self) -> None:
        assert verify_v2_replay(REPO) == RUN003_ID

    def test_tampered_results_alias_is_rejected(self, tmp_path: Path) -> None:
        clone = _tampered_clone(
            tmp_path, "research/m3a/development_results.json", lambda b: b + b"\n"
        )
        # Rejected either by the strict v2 loader or by the byte comparison;
        # both are ReplayV2Error/DevelopmentResultsV2Error (RuntimeError).
        with pytest.raises(RuntimeError):
            verify_v2_replay(clone)

    def test_tampered_report_alias_is_rejected(self, tmp_path: Path) -> None:
        clone = _tampered_clone(tmp_path, "research/m3a/development_report.md", lambda b: b + b"\n")
        with pytest.raises(ReplayV2Error, match="does not match the committed bytes"):
            verify_v2_replay(clone)

    def test_tampered_immutable_archive_is_rejected(self, tmp_path: Path) -> None:
        rel = f"research/m3a/experiments/{RUN003_ID}/development_results.json"
        clone = _tampered_clone(tmp_path, rel, lambda b: b + b"\n")
        with pytest.raises(ReplayV2Error, match="does not match the committed bytes"):
            verify_v2_replay(clone)


class TestRun003LeftTheFirewallSealed:
    """run-003 appended three registry events and touched no forbidden partition:
    the frozen v1 prefix is intact and both access ledgers are still empty."""

    def test_registry_v1_prefix_is_byte_unchanged(self) -> None:
        raw = (REPO / EXPERIMENT_REGISTRY_RELPATH).read_bytes()
        lines = [ln for ln in raw.split(b"\n") if ln]
        # Six v1 lines (run-001/002) + run-003 registered/started/completed.
        assert len(lines) == 9
        prefix = b"".join(ln + b"\n" for ln in lines[:6])
        assert sha256_bytes(prefix) == REGISTRY_PREFIX_SHA256

    def test_both_access_ledgers_are_still_byte_empty(self) -> None:
        assert GATE_LEDGER.read_bytes() == b""
        assert HOLDOUT_LEDGER.read_bytes() == b""
        assert sha256_bytes(GATE_LEDGER.read_bytes()) == EMPTY_SHA
        assert sha256_bytes(HOLDOUT_LEDGER.read_bytes()) == EMPTY_SHA
