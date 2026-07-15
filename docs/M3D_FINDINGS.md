# M3D Findings — Independent Red-Team Review

Three independent, read-only red teams audited Milestone 3D against a disposable
full clone of the repository (no real file was modified during the audit). Each
classified findings A (cosmetic) / B (minor) / C (should fix) / D (HARD STOP).

## Verdict

**No Class D finding.** All three teams independently confirmed the core
integrity holds: M3D computes no strategy signal, return, metric, ranking, P&L,
weight, position, or promotion decision; the two sealed access ledgers and the
prospective evaluation ledger are byte-empty; the cohort is immature (3/365) and
never evaluation-authorized; the M3C candidate is still recorded rejected; the
canonical cohort re-derives byte-for-byte from committed raw bytes and is
genuinely non-overlapping with the frozen M2B data; and the acquisition network
boundary is fully retired at HEAD.

- **Red Team A (provenance & data integrity): Class C.** The transformation,
  receipt→raw byte pinning, segment hash-chain, non-overlap, and maturity
  assessment are all sound; the committed genesis and audit attempts are genuinely
  independent and reproduce the same canonical content.
- **Red Team B (governance & evaluation-prohibition firewall): Class C.** Maturity
  and authorization cannot be forced; a false "sealed partition was used" claim is
  caught; the research train is correctly declared exhausted.
- **Red Team C (security, supply-chain & reproducibility): Class C.** No live
  network or write capability, no socket in the runner, deterministic offline
  replay that hard-stops on every contamination class, and a status CLI that
  leaks nothing.

## Class C findings and their fixes (commit "red-team fixes — close the defense-in-depth gaps")

| # | Finding | Fix |
|---|---------|-----|
| A-C1 | The reacquisition-audit independence check was vacuous — it compared only `plan_sha256`, which differs by `attempt_id` by construction, so a copied/non-independent second attempt passed. | `reacquisition_audit.py` now enforces distinct `source_commit` AND distinct `workflow_run_id`; a non-independent audit is rejected (regression test added). |
| B-C3 | The verifier's forbidden-field scan matched a narrow substring list, inspected keys only, and covered only 2 of 5 artifacts — a `max_drawdown`/`cagr` field (or a value-borne token) could be smuggled. | Expanded the metric vocabulary, match keys **and** string values, over **all five** published artifacts (regression tests added). |
| B-C2 | The verifier's prohibited-import scan was a deny-list with real gaps (e.g. `fractional.accounting`). | Replaced with an **allow-list** mirroring the architecture test — a newly-added engine module cannot slip a gap (regression test added). |
| B-C1 / C-C1 / C-C2 | The verifier's workflow scan globbed only `*.yml`, kept a now-dead `m3d-acquire.yml` exception, and checked only `contents: write`; `test_workflow_security.py` globbed only `*.yml`. | The verifier and the tests glob `*.yml` **and** `*.yaml`; the dead exception is removed; the verifier also rejects a Coinbase host, a secret reference, and a force push (regression tests added). |
| A-B1 | The delivered cohort length was not bound to the pre-registered plan window — a truncated tail would be accepted. | `raw_bundle.py` now asserts `row_count == expected_bucket_count` and `last_open == window_end - 1 day` (regression test added). |
| A-A1 | The cohort manifest omitted the specification-catalog hash. | Added `specification_catalog_sha256` to the manifest provenance. |
| B-B1 | The maturity floor guard compared the imported constant to itself (inert). | Pin the floor against a hard literal `365`, independent of the constant. |
| C-B2 | The tracked-tree-unchanged assertion ran in only one of three replay jobs. | Added it to both compat-replay jobs. |
| C-B1 | The M3D piped-installer test was a brittle whole-file short-circuit. | Replaced with a robust per-line scan. |
| B-A1 | Two verifier checks shared the `04_` label. | Renumbered to 25 unique labels (asserted unique in tests). |

## Inherent limitation (by design, not a defect)

The prospective cohort is self-anchoring: future-only candle bytes are bound to
their committed receipts, with no external value oracle — correct for data that no
prior milestone can pin. An offline verifier proves internal consistency and
reproducibility, not authenticity against an outside source; a committer with
repository-write access who consistently regenerated *both* independent attempts
and every derived artifact would replay clean. The two genuinely independent
acquisitions — distinct source commits, distinct workflow-run ids, captured at
acquisition time and now enforced — are the strongest authenticity control
available offline, and the recorded workflow-run ids are the external-audit hook.
This is documented, not hidden.
