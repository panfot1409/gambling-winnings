# Milestone 3B — fractional execution-risk run-001 artifacts

This directory holds the one preregistered fractional experiment
(`m3b-fractional-execution-risk-v1-run-001`) and the additive provenance
artifacts added by the trust-boundary closure. **Nothing here is edited in place**
— the run's financial bytes are immutable history; the closure only *adds*
independently verifiable records.

## Frozen run-001 (immutable, single-use)

| file | what it is |
| --- | --- |
| `experiment_registry.jsonl` | append-only, hash-chained registry: `registered` → `started` → `completed` |
| `fractional_protocol.json` | the pre-registered protocol (strategies, cost scenarios, bindings) |
| `fractional_results.json` | the strict, symmetric 75-cell + 15-aggregate results model |
| `fractional_report.md` | the deterministic Markdown report (re-renders byte-for-byte from the results) |
| `experiments/run-001/manifest.json` | the v1 manifest binding the artifact digests to the registry |

## Additive closure artifacts

| file / dir | closure | what it proves |
| --- | --- | --- |
| `experiments/run-001/immutable-v2/` | R2 | a genuine per-run immutable body: byte-identical copies of the results + report plus `archive_v2.json` binding their digests to the manifest and registry |
| `execution_trace_commitments.json` | R11 | size-bounded, replay-reconstructible SHA-256 commitments to every cell's full per-bar execution trace |
| `run001_legacy_completion_audit.json` | R1 | records that run-001 predates the durable completion-intent mechanism, so its completeness rests on the registry `completed` event + `verify_published_run` |
| `artifact_annotations.jsonl` | §8 | append-only, hash-chained index of the additive artifacts above (each pins its target's digest) |
| `errata/` + `artifact_errata.jsonl` | R10 | append-only erratum correcting the report's overbroad cost-monotonicity claim, with the complete full-precision cell-wise counterexample |

## Verifying everything

```
# byte-for-byte reproduction of the published run (dual-state)
python -m eth_research.fractional.replay --repo-root . --check

# comprehensive 24-point (25 with --deep) verification of the whole run archive
python -m eth_research.fractional.verify_run_archive --repo-root . --deep

# crash-recovery status (there is no pending publication for run-001)
python -m eth_research.fractional.recovery --repo-root . --status
```

The two sealed access ledgers (`research/m3a/development_gate_access.jsonl` and
`research/m2b/test_evaluations.jsonl`) are and remain **byte-empty**: the
development gate and the final holdout were never evaluated.
