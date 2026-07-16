# research/m3d — Prospective Evidence & Governance Artifacts

Data-only, governance-only artifacts for Milestone 3D. Nothing here evaluates,
ranks, tunes, or promotes any strategy; every file re-derives byte-for-byte from
committed bytes and is checked by `python -m eth_research.m3d.verify_m3d_program`.

## Governance / research-history

| File | What it is |
|------|-----------|
| `research_program_snapshot.json` | Machine-verifiable snapshot of the M2B/M3A/M3B/M3C research program. |
| `research_specification_catalog.json` | Catalog of every benchmark/strategy specification, cost scenario, and risk overlay exercised. |
| `research_multiplicity.jsonl` | Append-only, hash-chained ledger of every research degree of freedom (honesty about the search surface, not a p-value correction). |
| `research_data_use.jsonl` | Append-only ledger of historical research data use + the sealed-partition firewall (development gate and final holdout are byte-empty). |
| `research_train_exhaustion.json` | The decision closing the research-train partition to new candidate research. |

## Prospective cohort

| File | What it is |
|------|-----------|
| `prospective_protocol.json` | Pre-registered cohort protocol (source, boundaries, 365-observation maturity floor). |
| `prospective_evaluations.jsonl` | The evaluation ledger — created **byte-empty** and never appended in M3D. |
| `raw/coinbase/<attempt>/acquisition_plan.json` | Committed, validated request plan (offline-computed windows). |
| `raw/coinbase/<attempt>/<candle>.json` | Retained raw Coinbase response bytes (genesis + independent audit). |
| `raw/coinbase/<attempt>/acquisition_receipt.json` | Strict receipt binding body hashes/lengths — never candle values. |
| `prospective_segments.jsonl` | Append-only hash-chained segment ledger (genesis sentinel + one segment). |
| `prospective_quality.json` | Integrity-only quality audit (zero structural errors; overlap-with-M2B is a HARD STOP). |
| `reacquisition_audit.json` | Proof the genesis and audit acquisitions reproduce identical canonical content. |
| `prospective_manifest.json` | The cohort provenance anchor: identity, boundaries, maturity, every provenance hash, ledger facts, and the governance flags (all false; `maturity_state: immature`, `evaluation_authorized: false`). |
| `publication_manifest.json` | Completeness marker binding every published artifact by hash. |

## Terminal state

The cohort holds **3** completed daily observations against a **365** floor — it is
**immature**, evaluation is **not authorized**, and no strategy was evaluated. See
`docs/M3D_ACQUISITION.md`, `docs/M3D_PROSPECTIVE_PROTOCOL.md`, and
`docs/M3D_THREAT_MODEL.md`.
