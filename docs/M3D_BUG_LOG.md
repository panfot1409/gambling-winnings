# M3D Bug Log

Defects found and fixed during Milestone 3D, most recent first. Each entry states
the symptom, the root cause, the fix, and the regression that pins it.

## B1 — Coinbase inclusive-end vs half-open window conflation (acquisition HARD STOP)

- **Symptom:** the first genesis acquisition run (`29422908037`) failed offline
  validation with `AcquisitionError: 1 row(s) at or after the declared window end
  (first offending epoch 1784073600)`. Epoch `1784073600` is `2026-07-15T00:00:00Z`
  — the still-forming candle for the acquisition day.
- **Root cause:** Coinbase's `/candles` `start`/`end` query parameters are
  **inclusive bucket opens**. The M3D acquisition plan set the request `end_param`
  equal to the half-open `window_end` (`2026-07-15`), so Coinbase returned the
  forming `2026-07-15` candle, which the strict adapter correctly rejected as being
  at/after the declared window end. The reviewed M2B adapter already documents the
  correct convention (`eth_research.data.coinbase._bind_request_metadata`: `start ==
  window_start`, `end == window_end - 1 day`). Three M3D sites conflated the
  inclusive request params with the half-open parse window; they were only
  coincidentally consistent while `end_param == window_end`.
- **Fix:** `acquisition_plan.py` now builds and validates `end_param` as
  `window_end - 1 day` (the last completed bucket open); `acquire_runner.py` and
  `raw_bundle.py` parse against the half-open plan window `[window_start,
  window_end)` rather than the inclusive request params (which remain provenance).
  The genesis plan was regenerated (`plan_sha256` changed to `4b2be218…`); the
  corrected genesis and the independent audit run then succeeded and matched.
- **Regression:** `tests/test_m3d_acquisition.py::test_plan_request_end_param_is_last_completed_bucket_open`
  and `::test_plan_rejects_end_param_equal_to_window_end`. The existing forming-candle
  rejection (`::test_verify_rejects_out_of_window_row`) remains as defense in depth.

## B2 — Trigger mechanism: `workflow_dispatch` not dispatchable off the default branch

- **Symptom:** dispatching `m3d-acquire.yml` returned HTTP 404 (`Resource not
  accessible` / workflow not found) because the workflow file lived only on the
  stacked feature branch.
- **Root cause:** GitHub only registers a `workflow_dispatch` workflow as
  dispatchable when it exists on the repository's default branch.
- **Fix:** adopt the reviewed M2B push-sentinel bootstrap — a `push` trigger scoped
  to the feature branch and to a single committed sentinel
  (`research/m3d/acquire.trigger`). Every other hardening property was unchanged.
  The workflow and sentinel were later retired (Milestone 3D section 25).

## Governance provenance cascade (design correction, not a runtime bug)

The data-use ledger initially carried a speculative conditional entry for the
prospective cohort keyed on the cohort manifest's existence. Because the exhaustion
decision binds the data-use ledger hash, materializing that entry would have forced
the exhaustion anchor to change. The data-use ledger is by its own contract a record
of **historical** research use (M2B/M3A/M3B/M3C); the future-only prospective
cohort's complete data-use record lives in the cohort manifest instead. The
speculative entry was removed, keeping the data-use ledger byte-frozen and the
governance graph acyclic.
