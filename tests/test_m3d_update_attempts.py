"""V2D growth-core tests: update-attempts ledger, plan dispatch, grown-tree replay.

Three claims are proven here, never mutating the real repository:

1. **The committed growth replays** — the committed ``update_attempts.jsonl``
   verifies as an append chain whose entries bind the governance-accepted update
   attempts (evidence directory, plan/receipt hashes, acceptance record), and
   every multi-attempt rebuild is byte-for-byte identical to the committed
   artifacts, so the growth machinery reproduces exactly the accepted state.
2. **The m3e→m3d plan bridge** — an M3E update plan built from the real accepted
   base is accepted verbatim by the m3d kind-dispatched loader (and refused when
   tampered), so a landed update attempt replays from committed bytes alone.
3. **A grown tree verifies end-to-end** — a synthetic update attempt (fabricated
   Coinbase-format raw bytes for the next due days) landed via the ledger + the
   deterministic rebuilds yields a tree on which the WHOLE m3d program, the m3e
   accepted base, and the V2D activation gate all pass with the grown row count —
   and every tamper (gap, ledger/bytes mismatch, raw flip) is refused.

Expectations for the real tree are DERIVED from the committed governance evidence
(the accepted base, the acceptance registry, and each acceptance record) so the
same semantic checks keep holding as future append-only proposals are accepted.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eth_research.m3d.acquisition_plan import (
    ENDPOINT,
    USER_AGENT,
    ProspectiveAcquisitionPlan,
    ProspectiveUpdatePlanView,
    load_prospective_acquisition_plan,
)
from eth_research.m3d.chain import PREVIOUS_FIELD
from eth_research.m3d.cohort import (
    MANIFEST_PATH,
    build_cohort_manifest_bytes,
    publish_prospective_cohort,
)
from eth_research.m3d.protocol import COHORT_START
from eth_research.m3d.quality import QUALITY_PATH, build_prospective_quality_bytes
from eth_research.m3d.receipt import ProspectiveAttemptReceipt, load_prospective_attempt_receipt
from eth_research.m3d.segment import (
    SEGMENTS_PATH,
    build_prospective_segments_bytes,
    verify_prospective_segments,
)
from eth_research.m3d.update_attempts import (
    UPDATE_ATTEMPTS_PATH,
    accepted_attempt_ids,
    build_accepted_raw_bundles,
    extend_update_attempts_bytes,
    load_update_attempt_entries,
)
from eth_research.m3d.validation import M3DValidationError, sha256_bytes
from eth_research.m3d.verify_m3d_program import verify_m3d_program
from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_PATH,
    build_accepted_base_bytes,
    verify_accepted_base,
)
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, build_update_plan

REPO_ROOT = Path(__file__).resolve().parents[1]

# Everything verify_m3d_program + the accepted base + the V2D gate transitively read
# (the four upstream evidence roots are small, ~2 MB total).
_TREE_COPY: tuple[str, ...] = (
    "research/m2b",
    "research/m3a",
    "research/m3b",
    "research/m3c",
    "research/m3d",
    "research/m3e/accepted_base.json",
    "governance/v2d/prospective_activation.json",
    ".github/workflows/m3e-prospective-update.yml",
)

_SOURCE_COMMIT = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

_ACCEPTANCE_REGISTRY = "research/m3e/acceptance_registry.jsonl"
_ACCEPTANCES_DIR = "research/m3e/acceptances"


def _registry_acceptances() -> list[dict[str, Any]]:
    """Acceptance entries of the committed governance registry, in append order."""
    raw = (REPO_ROOT / _ACCEPTANCE_REGISTRY).read_text()
    records = [json.loads(line) for line in raw.splitlines() if line]
    acceptances = [r for r in records if r.get("entry_kind") == "acceptance"]
    assert acceptances, "the acceptance registry must record the accepted growth"
    return acceptances


def _acceptance_document(registry_entry: dict[str, Any]) -> dict[str, Any]:
    """Load one acceptance record and cross-check the registry's binding to it."""
    proposal_id = str(registry_entry["proposal_id"])
    doc: dict[str, Any] = json.loads(
        (REPO_ROOT / _ACCEPTANCES_DIR / proposal_id / "acceptance.json").read_text()
    )
    assert doc["proposal_id"] == proposal_id
    assert doc["acceptance_sha256"] == registry_entry["acceptance_sha256"]
    return doc


def _plus_days(open_z: str, days: int) -> str:
    return (pd.Timestamp(open_z) + pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact_day(open_z: str) -> str:
    return open_z[:10].replace("-", "")


def _as_of_after(last_open: str, days: int) -> str:
    """A 03:00Z instant ``days`` after ``last_open`` — safely past the settle delay,
    so exactly the ``days - 1`` candles after ``last_open`` are due."""
    return (pd.Timestamp(last_open) + pd.Timedelta(days=days)).strftime("%Y-%m-%dT03:00:00Z")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in _TREE_COPY:
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return tmp_path


# --------------------------------------------------------------------------------------------------
# 1. The committed growth replays (real tree, read-only)
# --------------------------------------------------------------------------------------------------


def test_committed_ledger_binds_every_accepted_update_attempt() -> None:
    # Loading verifies the hash chain, the pinned genesis sentinel, and contiguity.
    entries = load_update_attempt_entries(REPO_ROOT)
    acceptances = _registry_acceptances()
    # Exactly one landed attempt per governance acceptance, in the same order.
    assert len(entries) == len(acceptances) >= 1
    assert [e["proposal_id"] for e in entries] == [a["proposal_id"] for a in acceptances]

    # Genesis is always first; every landed update attempt follows in ledger order.
    assert accepted_attempt_ids(REPO_ROOT) == [
        "coinbase-eth-usd-prospective-genesis-001",
        *(str(e["attempt_id"]) for e in entries),
    ]

    # The newest entry binds the newest acceptance record and its committed
    # attempt evidence directory, byte-for-byte.
    acceptance = _acceptance_document(acceptances[-1])
    newest = entries[-1]
    assert newest["proposal_id"] == acceptance["proposal_id"]
    assert newest["plan_sha256"] == acceptance["update_plan_sha256"]
    interval = acceptance["append_interval"]
    assert newest["first_open"] == interval["first_open"]
    assert newest["last_open"] == interval["last_open"]
    assert newest["row_count"] == interval["row_count"]
    raw_dir = REPO_ROOT / f"research/m3d/raw/coinbase/{newest['attempt_id']}"
    assert raw_dir.is_dir()
    assert sha256_bytes((raw_dir / "acquisition_receipt.json").read_bytes()) == str(
        newest["receipt_sha256"]
    )
    receipt = load_prospective_attempt_receipt(raw_dir / "acquisition_receipt.json")
    assert receipt.plan_sha256 == newest["plan_sha256"]

    # The segment chain verifies with the genesis segment first and exactly one
    # extra segment per committed update attempt.
    records = verify_prospective_segments(REPO_ROOT)
    segments = [r for r in records if r.get("entry_kind") == "segment"]
    assert records[1] == segments[0]  # the genesis segment directly follows the sentinel
    assert segments[0]["segment_id"] == "prospective-segment-000"
    assert segments[0]["first_open"] == COHORT_START
    assert len(segments) == 1 + len(entries)

    # The grown cohort is the genesis rows plus every attested appended window.
    bundles, _ = build_accepted_raw_bundles(REPO_ROOT)
    base = verify_accepted_base(REPO_ROOT)
    assert sum(b.row_count for b in bundles) == base.row_count
    assert base.row_count == acceptance["new_accepted"]["row_count"]
    assert base.last_open == acceptance["new_accepted"]["last_open"]
    assert base.last_open == newest["last_open"]


def test_committed_rebuilds_stay_byte_identical_after_growth() -> None:
    for rel, rebuild in (
        (SEGMENTS_PATH, build_prospective_segments_bytes),
        (QUALITY_PATH, build_prospective_quality_bytes),
        (MANIFEST_PATH, build_cohort_manifest_bytes),
        (ACCEPTED_BASE_PATH, build_accepted_base_bytes),
    ):
        assert (REPO_ROOT / rel).read_bytes() == rebuild(REPO_ROOT), rel


# --------------------------------------------------------------------------------------------------
# 2. The m3e update plan is accepted verbatim by the m3d loader (and refused tampered)
# --------------------------------------------------------------------------------------------------


def _real_update_plan(days_after_last: int = 3) -> ProspectiveUpdatePlan:
    base = verify_accepted_base(REPO_ROOT)
    decision = plan_update_window(base, _as_of_after(base.last_open, days_after_last))
    assert not decision.is_noop
    assert decision.expected_new_buckets == days_after_last - 1
    return build_update_plan(base, decision)


def test_m3e_update_plan_loads_through_the_m3d_dispatcher(tmp_path: Path) -> None:
    plan = _real_update_plan()
    path = tmp_path / "acquisition_plan.json"
    path.write_bytes(plan.to_json_bytes())
    view = load_prospective_acquisition_plan(path)
    assert isinstance(view, ProspectiveUpdatePlanView)
    assert view.plan_sha256 == plan.plan_sha256
    assert [w["raw_filename"] for w in view.windows] == [w["raw_filename"] for w in plan.windows]


def test_tampered_update_plan_hash_is_refused(tmp_path: Path) -> None:
    plan = _real_update_plan()
    doc = json.loads(plan.to_json_bytes())
    doc["expected_total_buckets"] = doc["expected_total_buckets"] + 1
    path = tmp_path / "acquisition_plan.json"
    path.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    with pytest.raises(M3DValidationError):
        load_prospective_acquisition_plan(path)


def test_genesis_plan_still_loads_as_v1(tmp_path: Path) -> None:
    src = REPO_ROOT / "research/m3d/raw/coinbase/coinbase-eth-usd-prospective-genesis-001"
    plan = load_prospective_acquisition_plan(src / "acquisition_plan.json")
    assert isinstance(plan, ProspectiveAcquisitionPlan)


# --------------------------------------------------------------------------------------------------
# 3. Synthetic landed update: the grown tree verifies end-to-end
# --------------------------------------------------------------------------------------------------


def _coinbase_raw_bytes(opens: list[str]) -> bytes:
    """Strictly-descending Coinbase candles [[t, low, high, open, close, volume]]."""
    rows = []
    for i, open_z in enumerate(reversed(opens)):
        t = int(pd.Timestamp(open_z).timestamp())
        px = 3000.0 + 10.0 * i
        rows.append([t, px - 5.0, px + 5.0, px, px + 1.0, 1000.0 + i])
    return json.dumps(rows).encode()


def _land_update(
    tree_root: Path, *, days_after_last: int, proposal_id: str = "m3e-update-fixture-001"
) -> str:
    """Fabricate + land one update attempt exactly as the reviewed path would.

    The as-of instant is derived from the tree's CURRENT accepted base, so exactly
    ``days_after_last - 1`` new settled days beyond its last open are landed.
    Returns the attempt id. Writes the raw evidence dir, appends the ledger entry,
    and rewrites every derived artifact via the deterministic builders (the same
    sequence the M3E staging step performs).
    """
    base = verify_accepted_base(tree_root)
    as_of = _as_of_after(base.last_open, days_after_last)
    decision = plan_update_window(base, as_of)
    plan = build_update_plan(base, decision)
    (window,) = plan.windows  # short due windows tile into exactly one request
    opens = [
        (pd.Timestamp(decision.first_missing_open) + pd.Timedelta(days=d)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        for d in range(decision.expected_new_buckets)
    ]
    raw = _coinbase_raw_bytes(opens)

    first_c = opens[0][:10].replace("-", "")
    last_c = opens[-1][:10].replace("-", "")
    attempt_id = (
        f"coinbase-eth-usd-prospective-update-{first_c}-{last_c}-{plan.idempotency_key[:16]}"
    )
    raw_dir = tree_root / f"research/m3d/raw/coinbase/{attempt_id}"
    raw_dir.mkdir(parents=True)
    (raw_dir / "acquisition_plan.json").write_bytes(plan.to_json_bytes())
    (raw_dir / str(window["raw_filename"])).write_bytes(raw)
    receipt = ProspectiveAttemptReceipt.from_mapping(
        {
            "schema_version": 1,
            "kind": "prospective_attempt_receipt",
            "package_version": "0.8.0",
            "attempt_id": attempt_id,
            "plan_sha256": plan.plan_sha256,
            "endpoint": ENDPOINT,
            "user_agent": USER_AGENT,
            "source_commit": _SOURCE_COMMIT,
            "workflow_run_id": "1",
            "runner_identity": "runner-a-fixture",
            "client_identity": "curl-fixture",
            "created_at_utc": as_of,
            "responses": [
                {
                    "ordinal": 0,
                    "raw_filename": str(window["raw_filename"]),
                    "start_param": str(window["start_param"]),
                    "end_param": str(window["end_param"]),
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "response_byte_length": len(raw),
                    "response_sha256": sha256_bytes(raw),
                    "retrieved_at": as_of,
                }
            ],
        }
    )
    (raw_dir / "acquisition_receipt.json").write_bytes(receipt.to_json_bytes())

    ledger_path = tree_root / UPDATE_ATTEMPTS_PATH
    existing = ledger_path.read_bytes() if ledger_path.exists() else None
    entries = load_update_attempt_entries(tree_root)
    entry: dict[str, Any] = {
        "schema_version": 1,
        "entry_kind": "update_attempt",
        "ordinal": len(entries) + 1,
        "attempt_id": attempt_id,
        "first_open": opens[0],
        "last_open": opens[-1],
        "row_count": len(opens),
        "plan_sha256": plan.plan_sha256,
        "receipt_sha256": sha256_bytes(receipt.to_json_bytes()),
        "proposal_id": proposal_id,
        "created_at_utc": as_of,
        "package_version": "0.7.0",
    }
    ledger_path.write_bytes(extend_update_attempts_bytes(existing, entry))

    # Rewrite the derived artifacts exactly as the staging step will: chain +
    # quality first (pure), then the transactional publication bundle, then the
    # accepted-base snapshot.
    (tree_root / SEGMENTS_PATH).write_bytes(build_prospective_segments_bytes(tree_root))
    (tree_root / QUALITY_PATH).write_bytes(build_prospective_quality_bytes(tree_root))
    publish_prospective_cohort(tree_root)
    (tree_root / ACCEPTED_BASE_PATH).write_bytes(build_accepted_base_bytes(tree_root))
    return attempt_id


def test_grown_tree_verifies_end_to_end(tree: Path) -> None:
    base0 = verify_accepted_base(tree)
    committed_ids = [str(e["attempt_id"]) for e in load_update_attempt_entries(tree)]
    attempt_id = _land_update(tree, days_after_last=3)  # lands exactly the next 2 days

    entries = load_update_attempt_entries(tree)
    assert [str(e["attempt_id"]) for e in entries] == [*committed_ids, attempt_id]
    bundles, _ = build_accepted_raw_bundles(tree)
    assert sum(b.row_count for b in bundles) == base0.row_count + 2  # accepted + 2 landed

    checks = verify_m3d_program(tree)
    assert len(checks) == 25
    base = verify_accepted_base(tree)
    assert base.row_count == base0.row_count + 2
    assert base.last_open == _plus_days(base0.last_open, 2)
    assert base.document["maturity_state"] == "immature"
    assert base.document["evaluation_authorized"] is False
    assert "update_attempts_ledger_sha256" in base.document["provenance"]

    # The V2D activation gate accepts the grown cohort (genesis anchor intact).
    from eth_research.v2d.activation import verify_activation

    _anchor, gate_base = verify_activation(
        tree,
        workflow_basename="m3e-prospective-update.yml",
        repository="panfot1409/gambling-winnings",
    )
    assert gate_base.row_count == base0.row_count + 2


def test_second_update_builds_on_the_grown_base(tree: Path) -> None:
    base0 = verify_accepted_base(tree)
    committed = len(load_update_attempt_entries(tree))
    _land_update(tree, days_after_last=3)  # lands 2 days
    grown_last = verify_accepted_base(tree).last_open
    second = _land_update(
        tree, days_after_last=3, proposal_id="m3e-update-fixture-002"
    )  # lands the next 2 days after the grown base
    assert verify_accepted_base(tree).row_count == base0.row_count + 4
    assert [e["ordinal"] for e in load_update_attempt_entries(tree)] == list(
        range(1, committed + 3)
    )
    first_c = _compact_day(_plus_days(grown_last, 1))
    last_c = _compact_day(_plus_days(grown_last, 2))
    assert second.startswith(f"coinbase-eth-usd-prospective-update-{first_c}-{last_c}-")
    assert len(verify_m3d_program(tree)) == 25


# --------------------------------------------------------------------------------------------------
# 4. Tamper matrix (all on the disposable grown tree)
# --------------------------------------------------------------------------------------------------


def test_gap_entry_is_refused(tree: Path) -> None:
    _land_update(tree, days_after_last=3)  # accepted through last_open + 2 days
    entries = load_update_attempt_entries(tree)
    accepted_last = str(entries[-1]["last_open"])
    # Forge a next entry that skips the day right after the accepted window
    # (starts two days after it): contiguity refusal.
    skipped_open = _plus_days(accepted_last, 2)
    day = _compact_day(skipped_open)
    ledger_path = tree / UPDATE_ATTEMPTS_PATH
    entry = {
        "schema_version": 1,
        "entry_kind": "update_attempt",
        "ordinal": len(entries) + 1,
        "attempt_id": f"coinbase-eth-usd-prospective-update-{day}-{day}-" + "0" * 16,
        "first_open": skipped_open,
        "last_open": skipped_open,
        "row_count": 1,
        "plan_sha256": "0" * 64,
        "receipt_sha256": "0" * 64,
        "proposal_id": "forged",
        "created_at_utc": _plus_days(accepted_last, 3),
        "package_version": "0.7.0",
    }
    ledger_path.write_bytes(extend_update_attempts_bytes(ledger_path.read_bytes(), entry))
    with pytest.raises(M3DValidationError, match="contiguous"):
        load_update_attempt_entries(tree)


def test_ledger_facts_must_match_the_bytes(tree: Path) -> None:
    _land_update(tree, days_after_last=3)
    ledger_path = tree / UPDATE_ATTEMPTS_PATH
    lines = ledger_path.read_bytes().decode().splitlines()
    # Re-append the newest entry with an inflated row_count/last_open but a valid
    # chain (the accepted prefix, including every prior entry, stays untouched).
    record = json.loads(lines[-1])
    del record[PREVIOUS_FIELD]
    record["row_count"] = int(record["row_count"]) + 1
    record["last_open"] = _plus_days(str(record["last_open"]), 1)
    prefix = ("\n".join(lines[:-1]) + "\n").encode()
    ledger_path.write_bytes(extend_update_attempts_bytes(prefix, record))
    with pytest.raises(M3DValidationError, match="does not match the bytes"):
        build_accepted_raw_bundles(tree)


def test_tampered_update_raw_byte_is_refused(tree: Path) -> None:
    attempt_id = _land_update(tree, days_after_last=3)
    raw_dir = tree / f"research/m3d/raw/coinbase/{attempt_id}"
    raw_files = [p for p in raw_dir.iterdir() if p.name.startswith("coinbase-eth-usd-1d")]
    (raw_file,) = raw_files
    raw_file.write_bytes(raw_file.read_bytes().replace(b"3000.0", b"3111.0", 1))
    with pytest.raises(M3DValidationError, match="SHA-256"):
        build_accepted_raw_bundles(tree)


def test_appending_preserves_the_exact_prefix(tree: Path) -> None:
    _land_update(tree, days_after_last=3)  # lands 2 days
    before = (tree / UPDATE_ATTEMPTS_PATH).read_bytes()
    _land_update(tree, days_after_last=2, proposal_id="m3e-update-fixture-002")  # lands 1 day
    after = (tree / UPDATE_ATTEMPTS_PATH).read_bytes()
    assert after.startswith(before)  # append-only: the accepted prefix never rewrites
