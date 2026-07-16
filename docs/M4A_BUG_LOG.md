# M4A bug log — red-team defects reproduced and fixed

Each entry below is a defect an independent auditor (red teams A / B / C) reproduced against
the Milestone 4A release candidate with a concrete exploit, together with its root cause and
the fix. Every fixed defect has a regression test in `tests/test_m4a_redteam_hardening.py`
(or a strengthened assertion in `tests/test_packaging.py` / `tests/test_m4a_security.py`) that
fails against the pre-fix code and passes after. No accepted M2B–M3F artifact was modified;
all fixes are in the M4A public surface (`api/`, `cli/`, `m4a/`), the scanner, and the tests.

## Class B — trust boundary / private-data safety

### F1 — a symlinked `dataset.file.path` read outside the config directory (holdout escape)
- **Auditor / class:** C / B (a config could read the sealed holdout or governed data).
- **Root cause:** `orchestrate._load_dataset` joined `base_dir / file_cfg.path` and read it with
  no realpath confinement; the textual config guard rejects a *literal* `research/` path but not
  a symlink whose name is innocuous.
- **Fix:** resolve `(base_dir / path)` and require it to stay within `base_dir.resolve()`; a
  symlink whose target escapes the config directory is refused with `DatasetError`.
- **Test:** `test_dataset_file_symlink_escaping_base_dir_is_refused`.

### F2 — an output bundle escaped `base_dir` via a symlinked parent directory
- **Auditor / class:** C / B (writes outside the intended output tree).
- **Root cause:** `publish_bundle` checked only the leaf `out.is_symlink()`; `mkdir(parents=True)`
  silently follows a symlinked parent. The config output path also had no confinement.
- **Fix:** `publish_bundle` refuses the output leaf or its nearest existing parent being a
  symlink; `execute_config` additionally confines the resolved config output within `base_dir`.
- **Tests:** `test_publish_bundle_refuses_symlinked_parent`,
  `test_config_output_symlink_escaping_base_dir_is_refused`.

### F3 — CLI `--output` bypassed the config guards; `--overwrite` could clobber a governed artifact
- **Auditor / class:** C / B (governance-guard bypass; enables an accepted-artifact overwrite).
- **Root cause:** `cmd_backtest_run` / `cmd_demo_generate` used `Path(args.output)` directly,
  never through a governance guard; the publisher has no `research/` awareness.
- **Fix:** an operator `--output` is refused when it resolves into the repository's governed
  `research/` tree or a `.git` directory (`_reject_governed_output`).
- **Tests:** `test_reject_governed_output_refuses_research_and_git`,
  `test_cli_demo_output_into_git_component_is_refused`.

### B1 — the distribution scanner and packaging test let a non-`.py` data file ride inside the package
- **Auditor / class:** B / B (scanner bypass; escalates to a raw-Coinbase leak on any data drop).
- **Root cause:** the scanner's per-package check admitted *any* file under `eth_research/` and
  denied only a fixed suffix list that omitted `.json` (and `.pkl`, `.npy`, `.arrow`, …); the raw
  Coinbase candle format is `.json`.
- **Fix:** invert the per-package rule to a **pure-Python allowlist** — only `.py` / `.pyi` and
  `py.typed` are admitted under the package tree; `test_packaging.py` mirrors it.
- **Tests:** `test_scanner_flags_data_json_inside_wheel_package`,
  `test_scanner_flags_data_file_inside_sdist_package`, `test_scanner_accepts_a_clean_crafted_wheel`.

### A1 — the `run_id` did not bind the warm-up context content (only its bar count)
- **Auditor / class:** A / B (tamper-evidence / identity gap).
- **Root cause:** `_run_id` folded in `context_bars` but no context fingerprint; two runs with the
  same length but different context prices shared a `run_id`.
- **Fix:** `ResearchRunSpec` records `context_fingerprint`, and `_run_id` now hashes the **entire**
  run spec (so context content, and also the previously-omitted `split`, are bound).
- **Tests:** `test_run_id_binds_context_fingerprint`, `test_run_id_binds_split_fractions`.

### A3 — `dataset_manifest_sha256` was recorded but bound by nothing and never verified
- **Auditor / class:** A / B (a documented binding that did not hold).
- **Root cause:** `_run_id` omitted `dataset_manifest_sha256` and `verify_run_receipt` never
  checked it, so it was freely forgeable while the receipt still verified.
- **Fix:** the manifest digest is folded into `_run_id`; tampering with it makes the receipt's
  `run_id` fail to recompute on `verify`.
- **Tests:** `test_run_id_binds_dataset_manifest_sha256`, `test_receipt_manifest_digest_tamper_is_detected`.

## Class C — robustness / taxonomy / defense-in-depth

### F4 — `publish_bundle(overwrite=True)` leaked `IsADirectoryError` when a target name was a directory
- **Fix:** an existing target that is not a regular file is a clean `OutputCollisionError` before
  the snapshot read. **Test:** `test_publish_bundle_refuses_overwriting_a_directory`.

### F7 — `result verify` / `receipt verify` used the base error (exit 1) for an unreadable input
- **Fix:** `_read_bytes` is called with the concrete taxonomy leaf, so a missing result exits 7 and
  a missing receipt/result exits 8. **Tests:** `test_result_verify_missing_file_uses_taxonomy_exit_code`,
  `test_receipt_verify_missing_file_uses_taxonomy_exit_code`.

### F8 — `doctor`'s "offline" check was hardcoded `True`
- **Fix:** `_offline_capability_status` is a real in-process check that no network / exchange /
  wallet client is imported. **Tests:** `test_doctor_offline_check_reports_the_real_state`,
  `test_offline_status_flips_when_a_network_client_is_imported`.

### F9 — the config `research/` / `.git` guard was case-sensitive
- **Fix:** the guard casefolds path components, so `Research/` and `.GIT/` are refused too.
  **Test:** `test_config_rejects_governed_paths_case_insensitively`.

### F10 — `backtest run` read the config file twice (a validate-then-bind TOCTOU)
- **Fix:** `load_config_source` reads the bytes once and returns `(config, raw)`; the receipt binds
  exactly the validated bytes. **Test:** `test_load_config_source_returns_the_exact_file_bytes`.

### A-C1 — dataset interval failures leaked a bare `ValueError` (taxonomy violation)
- **Fix:** `frame_interval` is wrapped so a too-short frame surfaces as `DatasetError`.
  **Tests:** `test_generate_synthetic_single_period_raises_dataset_error`,
  `test_chronological_split_one_row_raises_dataset_error`.

### A-C2 — `StrategySpec` was not an object-level canonical fixed point
- **Fix:** `__post_init__` stores parameters sorted, so `x == StrategySpec.from_dict(x.to_dict())`.
  **Test:** `test_strategyspec_is_object_level_fixed_point`.

### A-C4 — public metrics were computed outside the engine `try` (latent bare-`ValueError` leak)
- **Fix:** `summarize` / `compute_fractional_metrics` now run inside the `try` that maps engine
  errors to `BacktestError`. (Defense-in-depth; not reachable with valid long-only inputs.)

### F5 / F6 — the source firewall was too narrow and its matcher was spelling-specific
- **Fix:** the AST firewall now scans the whole offline runtime (adding `data/`, `strategies/`,
  `fractional/`, and the core helpers), adds `subprocess` to the forbidden imports, and resolves
  aliased / `from`-imports and bare `import subprocess` rather than only dotted spellings. The
  accepted governance modules (`m3*`, `gitcheck`, `*_register`, `*_report`) legitimately shell out
  to git and are covered by their own accepted firewalls, so they stay out of the offline-runtime
  scan. (Strengthened `tests/test_m4a_security.py`.)
