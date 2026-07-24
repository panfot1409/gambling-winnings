"""V2D growth-core tests: update-attempts ledger, plan dispatch, grown-tree replay.

Three claims are proven here, none touching the real repository:

1. **Byte-neutrality at zero updates** — with no ``update_attempts.jsonl``, every
   multi-attempt rebuild is byte-for-byte identical to the committed genesis-only
   artifact, so the growth machinery changes nothing until an update lands.
2. **The m3e→m3d plan bridge** — an M3E update plan built from the real accepted
   base is accepted verbatim by the m3d kind-dispatched loader (and refused when
   tampered), so a landed update attempt replays from committed bytes alone.
3. **A grown tree verifies end-to-end** — a synthetic update attempt (fabricated
   Coinbase-format raw bytes for the next due days) landed via the ledger + the
   deterministic rebuilds yields a tree on which the WHOLE m3d program, the m3e
   accepted base, and the V2D activation gate all pass with the grown row count —
   and every tamper (gap, ledger/bytes mismatch, raw flip) is refused.
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
from eth_research.m3d.quality import QUALITY_PATH, build_prospective_quality_bytes
from eth_research.m3d.receipt import ProspectiveAttemptReceipt
from eth_research.m3d.segment import SEGMENTS_PATH, build_prospective_segments_bytes
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
# 1. Byte-neutrality at zero update attempts (real tree, read-only)
# --------------------------------------------------------------------------------------------------


def test_zero_updates_leave_every_rebuild_byte_identical() -> None:
    assert load_update_attempt_entries(REPO_ROOT) == []
    assert accepted_attempt_ids(REPO_ROOT) == ["coinbase-eth-usd-prospective-genesis-001"]
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


def _real_update_plan(as_of: str = "2026-07-17T03:00:00Z") -> ProspectiveUpdatePlan:
    base = verify_accepted_base(REPO_ROOT)
    decision = plan_update_window(base, as_of)
    assert not decision.is_noop
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
    tree_root: Path, *, as_of: str, proposal_id: str = "m3e-update-fixture-001"
) -> str:
    """Fabricate + land one update attempt exactly as the reviewed path would.

    Returns the attempt id. Writes the raw evidence dir, appends the ledger entry,
    and rewrites every derived artifact via the deterministic builders (the same
    sequence the M3E staging step performs).
    """
    base = verify_accepted_base(tree_root)
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
    attempt_id = _land_update(tree, as_of="2026-07-17T03:00:00Z")  # lands 07-15..07-16

    entries = load_update_attempt_entries(tree)
    assert [e["attempt_id"] for e in entries] == [attempt_id]
    bundles, _ = build_accepted_raw_bundles(tree)
    assert sum(b.row_count for b in bundles) == 5  # 3 genesis + 2 landed

    checks = verify_m3d_program(tree)
    assert len(checks) == 25
    base = verify_accepted_base(tree)
    assert base.row_count == 5
    assert base.last_open == "2026-07-16T00:00:00Z"
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
    assert gate_base.row_count == 5


def test_second_update_builds_on_the_grown_base(tree: Path) -> None:
    _land_update(tree, as_of="2026-07-17T03:00:00Z")
    second = _land_update(
        tree, as_of="2026-07-19T03:00:00Z", proposal_id="m3e-update-fixture-002"
    )  # lands 07-17..07-18
    assert verify_accepted_base(tree).row_count == 7
    assert [e["ordinal"] for e in load_update_attempt_entries(tree)] == [1, 2]
    assert second.startswith("coinbase-eth-usd-prospective-update-20260717-20260718-")
    assert len(verify_m3d_program(tree)) == 25


# --------------------------------------------------------------------------------------------------
# 4. Tamper matrix (all on the disposable grown tree)
# --------------------------------------------------------------------------------------------------


def test_gap_entry_is_refused(tree: Path) -> None:
    _land_update(tree, as_of="2026-07-17T03:00:00Z")  # accepted through 07-16
    # Forge a second entry that skips 07-17 (starts at 07-18): contiguity refusal.
    ledger_path = tree / UPDATE_ATTEMPTS_PATH
    entry = {
        "schema_version": 1,
        "entry_kind": "update_attempt",
        "ordinal": 2,
        "attempt_id": "coinbase-eth-usd-prospective-update-20260718-20260718-" + "0" * 16,
        "first_open": "2026-07-18T00:00:00Z",
        "last_open": "2026-07-18T00:00:00Z",
        "row_count": 1,
        "plan_sha256": "0" * 64,
        "receipt_sha256": "0" * 64,
        "proposal_id": "forged",
        "created_at_utc": "2026-07-19T00:00:00Z",
        "package_version": "0.7.0",
    }
    ledger_path.write_bytes(extend_update_attempts_bytes(ledger_path.read_bytes(), entry))
    with pytest.raises(M3DValidationError, match="contiguous"):
        load_update_attempt_entries(tree)


def test_ledger_facts_must_match_the_bytes(tree: Path) -> None:
    _land_update(tree, as_of="2026-07-17T03:00:00Z")
    ledger_path = tree / UPDATE_ATTEMPTS_PATH
    raw = ledger_path.read_bytes()
    # Rewrite the entry with an inflated row_count/last_open but a valid chain.
    lines = raw.decode().splitlines()
    record = json.loads(lines[1])
    del record[PREVIOUS_FIELD]
    record["row_count"] = 3
    record["last_open"] = "2026-07-17T00:00:00Z"
    ledger_path.write_bytes(extend_update_attempts_bytes(None, record))
    with pytest.raises(M3DValidationError, match="does not match the bytes"):
        build_accepted_raw_bundles(tree)


def test_tampered_update_raw_byte_is_refused(tree: Path) -> None:
    attempt_id = _land_update(tree, as_of="2026-07-17T03:00:00Z")
    raw_dir = tree / f"research/m3d/raw/coinbase/{attempt_id}"
    raw_files = [p for p in raw_dir.iterdir() if p.name.startswith("coinbase-eth-usd-1d")]
    (raw_file,) = raw_files
    raw_file.write_bytes(raw_file.read_bytes().replace(b"3000.0", b"3111.0", 1))
    with pytest.raises(M3DValidationError, match="SHA-256"):
        build_accepted_raw_bundles(tree)


def test_appending_preserves_the_exact_prefix(tree: Path) -> None:
    _land_update(tree, as_of="2026-07-17T03:00:00Z")
    before = (tree / UPDATE_ATTEMPTS_PATH).read_bytes()
    _land_update(tree, as_of="2026-07-18T03:00:00Z", proposal_id="m3e-update-fixture-002")
    after = (tree / UPDATE_ATTEMPTS_PATH).read_bytes()
    assert after.startswith(before)  # append-only: the accepted prefix never rewrites
