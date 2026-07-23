# V2C OQ — Crash / Recovery Model

The V2C offline operational qualification is **crash-safe by construction**: a run that dies after
its result is published is finalized **without recomputation**, and a run that dies earlier leaves
the append-only registry in a state the recovery CLI can classify unambiguously. Recovery never
re-executes the qualification and never recomputes a digest — it only re-appends a terminal event
that was already durably recorded.

## 1. The durable-intent protocol

A qualification reaches its terminal `completed` event through a two-phase, idempotent handshake:

1. **Publish** the immutable archive (`oq_result.json`, `oq_report.md`, `oq_archive_manifest.json`)
   into the run directory — write-once; existing per-run paths are never overwritten.
2. **Write the completion intent** (`governance/v2c/oq_completion_intent.json`): a small record that
   binds the five terminal digests, the `qualified` verdict, and the `prev_hash` of the durable
   `started` registry event. The intent is the commitment that the run *will* complete with exactly
   these bytes.
3. **Finalize**: append the `completed` event to `governance/v2c/oq_registry.jsonl` (chaining onto
   the `started` event's hash) and clear the intent.

A crash can land between any two of these steps. Because the intent records the terminal digests
before the registry event is appended, finalize is a pure, calculation-free re-application of a
recorded fact — not a re-run.

## 2. Recovery states (`finalize.assess` / the `recover` CLI)

`assess(repo_root, registry)` classifies the tree into exactly one state; `finalize(...)` performs
the append when (and only when) the state permits it:

| State                 | Meaning                                                              | `recover` action |
|-----------------------|---------------------------------------------------------------------|------------------|
| `no_intent`           | No pending intent (fresh, or already finalized+cleared).            | nothing to do    |
| `finalizable`         | Intent present, archive present, registry is exactly `registered → started`. | append `completed` |
| `not_finalizable`     | Intent present but archive incomplete, or the intent's `prev_hash` does not chain onto the `started` event. | refuse (fail-closed) |
| `finalized` / `already_finalized` | The `completed` event is already present. | idempotent no-op |

The finalizer is **fail-closed**: a missing/incomplete archive (`not_finalizable`, "incomplete")
or a mismatched started-chain (`not_finalizable`, "chains onto") is refused rather than guessed. It
will never fabricate a `completed` event, and it will never overwrite one.

## 3. What recovery deliberately does NOT do

- It does **not** re-execute the runner or recompute any digest — the terminal digests come from the
  durably-written intent, and the deep verifier independently re-derives them afterward.
- It does **not** reset the one-shot budget. Even if the registry were truncated to byte-empty to
  feign a pristine state, the surviving published archive trips the orchestrator's
  `no_prior_run_artifacts` gate, which refuses any re-register/re-start over an existing run.
- It does **not** touch any sealed partition.

## 4. The committed run's recovery posture

The committed run (`v2c_offline_operational_qualification_run_001`) finalized cleanly, so:

- The completion intent was **consumed** at finalize — `governance/v2c/oq_completion_intent.json`
  is absent.
- `recover --repo-root .` (assess) reports `no_intent`: there is nothing to finalize.
- The registry chain is complete (`registered → started → completed`, verdict `qualified`) and the
  archive is present — a crash-recovery on this tree is a no-op.

`tests/test_v2c_oq_committed_run.py::test_recover_is_a_noop_no_pending_intent` certifies this.

## 5. Recovering a crashed run in practice

```
# Inspect the state without changing anything:
python -m eth_research.v2c.oq.cli recover --repo-root .

# If it reports 'finalizable', complete it (calculation-free append of the recorded event):
python -m eth_research.v2c.oq.cli recover --repo-root . --finalize
```

If `recover` reports `not_finalizable`, the archive is incomplete or the intent does not chain onto
the durable `started` event — do not force it; investigate the archive and the registry chain. The
qualification is one-shot, so a genuinely corrupted run is not silently re-run; it is surfaced for
human review.
