"""No document may infer GitHub repository visibility from a PyPI classifier.

The STOP-1 defect had two halves. The code half — ``_repository_private`` returning
``"Private :: Do Not Upload" in pyproject.toml`` — is fixed and pinned by
``tests/test_v2f_containment_mutations.py``. This file pins the documentation half:
five committed audit records asserted the repository was private *and cited the
classifier as the reason*, while the GitHub API reported ``private: false``.

Those records are dated attestations, so they are corrected by a marked erratum at the
point of the claim rather than rewritten — a silent edit would falsify what the auditors
actually believed at the time, and the incident record is only legible if the wrong
claims are still visible next to their corrections.

Two rules, in opposite directions, because either alone is easy to satisfy dishonestly:

* every document that makes the inference must carry an erratum (deleting the claim is
  not a way to pass — the claim must still be there, marked);
* no document outside that known set may make the inference at all, so the correction
  cannot be undone by writing a fresh document that repeats it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

CLASSIFIER = "Private :: Do Not Upload"
ERRATUM_MARK = "**Erratum, 2026-07-28 (V2F-R).**"

#: Documents that inferred GitHub visibility from the packaging classifier, with the
#: exact defective claim each one made. Every entry must still contain its claim AND an
#: erratum; the pairing is what makes the record honest rather than merely tidy.
CORRECTED: dict[str, str] = {
    "V2_FABLE5_THREAT_MODEL.md": f"The repository is **private** (`{CLASSIFIER}`; no license).",
    "V2_PAPER_READINESS_GAP.md": f"| `repository_private` | **true** | — (`{CLASSIFIER}`",
    "V2C_TERMINAL_AUDIT.md": (
        f"The repository is private (`pyproject.toml` classifier `{CLASSIFIER}`)"
    ),
    "V2C_INDEPENDENT_ACCEPTANCE_AUDIT.md": f"| Repository | private (`{CLASSIFIER}`)",
    "V2_FABLE5_TERMINAL_AUDIT.md": f"carries the `{CLASSIFIER}` classifier (private)",
    # Found by this scanner, not by the auditor who reported "five documents". The
    # sixth is milder — it conflates packaging status with repository visibility in
    # passing rather than asserting privacy outright — but it is the same inference.
    "V2A_EVAL_LICENSE_DRAFT.md": f"the repository stays `{CLASSIFIER}`",
}

#: The inference itself: a sentence that ties repository/GitHub privacy to the classifier.
#: Deliberately narrow — statements *about the classifier* ("pyproject.toml carries the
#: guard", "no license field") are true and must keep passing, or the rule would push
#: authors to delete accurate packaging facts.
INFERENCE = re.compile(
    r"(?:repositor(?:y|ies)|github)[^.\n|]{0,80}privat|privat[^.\n|]{0,80}(?:repositor(?:y|ies)|github)",
    re.IGNORECASE,
)


def _docs() -> list[Path]:
    return sorted(DOCS.rglob("*.md"))


@pytest.mark.parametrize("name", sorted(CORRECTED))
def test_each_defective_claim_is_still_present_and_carries_an_erratum(name: str) -> None:
    text = (DOCS / name).read_text(encoding="utf-8")
    assert CORRECTED[name] in text, (
        f"{name}: the original defective claim was edited away or reworded. Corrections here "
        f"are append-only: the claim stays, the erratum explains it."
    )
    assert ERRATUM_MARK in text, (
        f"{name}: makes the classifier→visibility inference with no erratum"
    )


def test_no_other_document_infers_visibility_from_the_classifier() -> None:
    """The rule generalizes, so the fix cannot be undone by a new document."""
    offenders: list[str] = []
    for path in _docs():
        if path.name in CORRECTED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if CLASSIFIER in line and INFERENCE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert offenders == [], (
        "these lines infer GitHub repository visibility from a PyPI trove classifier:\n  "
        + "\n  ".join(offenders)
    )


def test_the_incident_record_is_the_single_referenced_source() -> None:
    """Every erratum points somewhere a reader can actually check."""
    incident = "docs/V2_PUBLIC_EXPOSURE_INCIDENT.md"
    assert (REPO_ROOT / incident).is_file()
    for name in CORRECTED:
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "V2_PUBLIC_EXPOSURE_INCIDENT.md" in text, f"{name}: erratum cites no source"


def test_the_control_accurate_packaging_statements_still_pass() -> None:
    """Without this, a rule that banned every mention of the classifier would look identical.

    These documents state true facts *about packaging* and must remain untouched by the
    rule; if this test ever fails, the pattern above has grown into a blanket ban.
    """
    for name in (
        "V1_PRIVATE_GA_TERMINAL_AUDIT.md",
        "V2A_PLAN.md",
        "V2A_HISTORICAL_REPLAY.md",
        "V2AB_STACK_ACCEPTANCE_AUDIT.md",
    ):
        path = DOCS / name
        assert CLASSIFIER in path.read_text(encoding="utf-8"), f"{name}: control text moved"
        for line in path.read_text(encoding="utf-8").splitlines():
            if CLASSIFIER in line:
                assert not INFERENCE.search(line), f"{name}: control line now makes the inference"
