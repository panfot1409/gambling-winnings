# Milestone 3A — closure bug log

Each defect was reproduced on starting HEAD
`8e076165ad07fcbeb4c5350e9d835439495b1489` before any fix. Reproductions live in
`tests/test_m3a_closure_defects.py`; as each defect is corrected the reproduction
is inverted into a regression test asserting the fixed behavior, and the fix
commit is recorded below.

| id | severity | reproduction (starting HEAD) | root cause | correction | regression test | fix commit |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | critical | `develop_m3a` never imports `experiment_registry`; `--write` reaches `generate()` and publishes with no registered/started event (`RETURN_CODE=0`, `REGISTRY_EXISTS=False`) | governance lives outside the publisher; the public write path has no registry gate | fail-closed orchestrator; `--write` real-data path removed; `started` durably appended before any real calculation | `test_public_real_data_write_requires_orchestrator`, orchestrator pre-start tests | _pending_ |
| R2 | high | `_atomic_write` renames each file separately with no fsync; injecting a failure before the 2nd write leaves `results=NEW, report=OLD` | the results+report batch is not atomic or rollback-safe; no fsync of file or directory | durable batch transaction: temp+fsync+ordered replace+manifest-last+dir fsync, reverse rollback restoring prior bytes | failure-injection matrix in `tests/test_m3a_transaction.py` | _pending_ |
| R3 | high | `load_development_results_payload` accepts `schema_version=999`, `fold_results="not-a-list-at-all"`, `bootstrap_cells=[{"forged":true}]` (`FORGED_RESULTS_ACCEPTED=True`) | it validates only the top-level key set and two counts; nested containers/identities/schema-version unchecked | results schema v2 with one strict symmetric construct+parse surface | `tests/test_results_v2.py` adversarial construct/parse tests | _pending_ |
| R4 | scientific | flat concatenation of five reset folds (226/225×4, block 30): 116/1097 seam-crossing starts (~10.57%), ~4.02 seam-crossing blocks per resample | `moving_block_bootstrap` samples over one concatenated series across reset seams | `fold-stratified-moving-block-bootstrap-v2` draws blocks strictly within a fold; v1 preserved | `tests/test_bootstrap_v2.py` sentinel no-seam-crossing tests | _pending_ |
| R5 | medium | `development_results.json` has `experiment_family_id` but no `experiment_id` | v1 results omit per-run identity | results v2 carries `experiment_id` on every artifact/event | `tests/test_results_v2.py::test_results_carry_experiment_id` | _pending_ |
| R6 | medium | only run-002 bodies exist at HEAD; run-001 recoverable only from Git | published bodies overwritten in place; no per-experiment archive | immutable `research/m3a/experiments/<id>/` archive + manifests + index; run-001/002 recovered and hash-proven | `tests/test_experiment_archive.py` | _pending_ |
| R7 | security | `ci.yml`/`m2b-replay.yml`/`m3a-replay.yml` run `curl -LsSf https://astral.sh/uv/0.8.17/install.sh \| sh` | unverified network content piped into a shell | full-SHA-pinned `astral-sh/setup-uv` (or SHA-256-verified binary) | `tests/test_workflow_security.py` (extended) | _pending_ |
| R8 | docs | "training rows"/"training window" implies a model fit that never occurs | fixed-rule strategies are not fitted | describe as fixed-rule rolling-origin OOS with expanding information sets | docs assertions in hygiene tests | _pending_ |
