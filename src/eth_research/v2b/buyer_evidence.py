"""V2B §25 — a buyer-evidence update that preserves every prior negative and keeps sell_ready false.

Reuses the accepted buyer-evaluation boundary (:mod:`eth_research.buyer` — evaluation contract,
claims catalog, readiness scorecard, factsheet) unchanged. The V2B update does not upgrade the
commercial posture: it stays ``not_sell_ready`` and ``sell_ready`` is explicitly false. It carries
forward every negative limitation the program has stated and adds V2B's own — cross-asset research
on the research-train only; a genuinely-new BTC information source; at most one candidate may be
forwarded to an *independent* development-gate review; nomination is not validation, forward
evidence, deployment readiness, or a performance claim; the cumulative family-wise correction over
M3A/B/C/V2A plus V2B governs any nomination. The artifact is frozen canonical JSON with a
fingerprint, so a buyer reads exactly the honest, negative-preserving posture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.buyer.claims import ClaimsCatalog
from eth_research.buyer.contract import EvaluationContract
from eth_research.buyer.factsheet import Factsheet
from eth_research.buyer.scorecard import ReadinessScorecard
from eth_research.v2.constitution import STANDING_POSTURE
from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, canonical_sha256

BUYER_EVIDENCE_SCHEMA_VERSION: int = 1
BUYER_EVIDENCE_RELPATH: str = "research/v2b/buyer_evidence.json"

#: Every negative limitation, prior and V2B, carried forward verbatim (order-stable).
V2B_LIMITATIONS: tuple[str, ...] = (
    "Research-stage only: the ETH/BTC/cash program is evaluated on the authorized research-train "
    "partition only; there is no out-of-sample, forward, walk-forward-live, or live evidence.",
    "V2A returned no nominated ETH-only candidate; that negative result stands as immutable "
    "research evidence and is not reopened.",
    "V2B adds a genuinely-new BTC information source and at most one cross-asset candidate may be "
    "forwarded to an INDEPENDENT development-gate review; a nomination is not validation, forward "
    "evidence, deployment readiness, capacity, or a performance claim.",
    "Any nomination must clear the cumulative family-wise multiplicity correction over all prior "
    "families (M3A/M3B/M3C/V2A) plus V2B — a stricter bar than any single milestone applied.",
    "Sealed partitions (development gate, final holdout, M2B test, M3D prospective, and every "
    "observation after the research cutoff) are never read; access ledgers stay byte-empty.",
    "Shadow operations are signal-only: no network, no orders, no credentials, and no money.",
    "sell_ready is false and remains false; nothing here is an offer to sell.",
)


class V2BBuyerEvidenceError(V2ValidationError):
    """The V2B buyer evidence violated its negative-preserving, not-sell-ready contract."""


def build_buyer_evidence() -> dict[str, Any]:
    """The frozen V2B buyer-evidence update (reuses the accepted buyer-evaluation objects)."""
    contract = EvaluationContract.current()
    claims = ClaimsCatalog.current()
    scorecard = ReadinessScorecard.current()
    factsheet = Factsheet.build(contract, claims, scorecard)
    if factsheet.posture != STANDING_POSTURE or scorecard.overall_posture != STANDING_POSTURE:
        raise V2BBuyerEvidenceError("posture is not not_sell_ready")
    doc = {
        "schema_version": BUYER_EVIDENCE_SCHEMA_VERSION,
        "kind": "v2b_buyer_evidence",
        "posture": STANDING_POSTURE,
        "sell_ready": False,
        "contract_fingerprint": contract.fingerprint(),
        "claims_fingerprint": claims.fingerprint(),
        "scorecard_fingerprint": scorecard.fingerprint(),
        "factsheet": factsheet.to_canonical(),
        "v2b_limitations": list(V2B_LIMITATIONS),
    }
    doc["evidence_fingerprint"] = canonical_sha256(doc)
    return doc


def render_buyer_evidence_bytes() -> bytes:
    return canonical_json_bytes(build_buyer_evidence())


def verify_buyer_evidence(repo_root: str | Path) -> None:
    """The committed buyer evidence reproduces and re-asserts not-sell-ready / sell_ready false."""
    committed = (Path(repo_root) / BUYER_EVIDENCE_RELPATH).read_bytes()
    if committed != render_buyer_evidence_bytes():
        raise V2BBuyerEvidenceError("committed buyer_evidence.json does not reproduce")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B buyer evidence (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / BUYER_EVIDENCE_RELPATH
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_buyer_evidence_bytes())
        print(f"wrote {BUYER_EVIDENCE_RELPATH}")
        return 0
    try:
        verify_buyer_evidence(args.repo_root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
