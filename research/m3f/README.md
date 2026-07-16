# Milestone 3F — verification & recovery artifacts

This directory holds the committed, byte-reproducible artifacts of the Milestone
3F verification and recovery layer. Every file here is a deterministic derivation
of already-committed repository state; none is a strategy result, and none is
catalogued by the freeze catalog (the M3F layer is self-verifying and is excluded
to avoid a catalog-of-itself circularity).

| File | What it is |
|---|---|
| `freeze_catalog.json` | Byte-level record binding every accepted M2B–M3E `research/` artifact to its source-freeze blob bytes, plus the source-tree fingerprint, sealed-ledger record, and expected governance state. |
| `honest_state.json` / `HONEST_STATE.md` | The repository's honest governance state, derived from committed bytes, failing closed on the four forever-invariants. |
| `dependency_inventory.json` | Locked dependency inventory derived from `uv.lock` + `pyproject.toml`. |
| `workflow_inventory.json` | Fail-closed inventory of every `.github/workflows/*` and its security-relevant facts. |
| `recovery_capsule_manifest.json` | Manifest pinning every file of the private recovery capsule (path, sha256, length) plus one capsule digest. |
| `RECOVERY_CAPSULE_NOTICE.md` | Notice describing the private recovery capsule and what it excludes. |
| `recovery_drill.json` | Deterministic record of the disposable-clone recovery drill (reconstruction + five failure drills). |

## Verify

```
uv run --no-sync python -m eth_research.m3f.audit --repo-root . --deep     # whole graph
uv run --no-sync python -m eth_research.m3f.recovery --repo-root . --deep  # recovery drill
python3 tools/m3f_independent_verify.py --repo-root . --json               # stdlib-only
```

See `docs/M3F_PLAN.md`, `docs/M3F_THREAT_MODEL.md`,
`docs/M3F_FREEZE_CATALOG_SPEC.md`, `docs/M3F_RECOVERY_RUNBOOK.md`, and
`docs/M3F_SUPPLY_CHAIN_AUDIT.md` for the full specification.

M3F evaluates nothing, activates nothing, and fetches nothing — it only proves,
from committed bytes, that the accepted stack is intact and that M3E remains
inactive.
