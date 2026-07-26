# V2F read-only preflight

Every fact below was measured against the live repository at the head named here, not carried
forward from a prior summary. Where a claim could not be verified, it says so.

## Repository identity and visibility

| fact | measured value |
| --- | --- |
| repository | `panfot1409/gambling-winnings` |
| **visibility** | **public** (`private: false`, `visibility: "public"`) |
| **forking** | **allowed** (`allow_forking: true`) |
| default branch | `main` |
| open issues / stars / forks | 1 / 1 / 0 |
| branch under work | `claude/v2e-proposal-acceptance-001` |
| HEAD | `0d01b085b047513a3e54dfa959f4aaa2c6cb8dff` |
| HEAD tree | `d8a2b7671ae1cbf0b74a0407efb76c8c5995f020` |
| `main` | `f42e5b5c8886128878e5e9daa45f10566c7426eb` |
| merge base | `f42e5b5c8886128878e5e9daa45f10566c7426eb` (equal to `main`) |
| working tree | clean, no untracked files |
| open PRs | one: **#22**, draft, `bot/m3e-prospective-update/…` → `main` |

The repository going public is the single largest change to the threat model this project has seen.
Everything committed — code, research data, governance evidence, workflow definitions and the whole
reachable history — is now world-readable, and forks are enabled, which puts every workflow trigger
into the fork threat model.

## Runtime and identity

| fact | measured value |
| --- | --- |
| authoritative interpreter | `/home/user/gambling-winnings/.venv/bin/python` |
| Python | CPython 3.12.3 |
| package version | `2.0.0.dev2` |
| git user | `Claude <noreply@anthropic.com>` |
| `commit.gpgsign` | `true` |
| `gpg` binary | present at `/usr/bin/gpg` |

Signing is configured and a `gpg` binary exists, but no commit produced in this session carries a
signature, so no signing key is usable in this environment. Recorded as a fact, not a defect; nothing
in the governance model depends on commit signatures.

## Sealed ledgers — the hard gate

All three are tracked, regular (non-symlink) files, exactly 0 bytes, hashing to the empty-string
SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`:

| ledger | bytes | tracked | type |
| --- | --- | --- | --- |
| `research/m2b/test_evaluations.jsonl` | 0 | yes | regular |
| `research/m3a/development_gate_access.jsonl` | 0 | yes | regular |
| `research/m3d/prospective_evaluations.jsonl` | 0 | yes | regular |

No sealed value has been read. No strategy evaluation exists.

## Derived governance flags

Every safety flag is false, from three independent artifacts:

| flag | source | value |
| --- | --- | --- |
| `evaluation_authorized` | `prospective_manifest.json`, `accepted_base.json` | `False` |
| `candidate_declared` | `prospective_manifest.json` | `False` |
| `promotion_decision_exists` | `prospective_manifest.json` | `False` |
| `strategy_evaluation_performed` | `prospective_manifest.json` | `False` |
| `new_strategy_evaluation_authorized` | `honest_state.json` | `False` |
| `any_gate_or_holdout_evaluated` | `honest_state.json` | `False` |
| `m3e_active` | `honest_state.json` | `False` |
| `maturity_state` | all three | `immature` |
| `m3c_candidate_verdict` | `honest_state.json` | `rejected_for_development_gate_promotion` |

There is no paper candidate, no paper activation authorization, no active paper trading and no
prospective-collection activity beyond the already-accepted cohort. `sell_ready` remains false.

### One apparent inconsistency, explained

`honest_state.json` records `m3d_cohort_row_count = 3` while `prospective_manifest.json` and
`accepted_base.json` record `row_count = 12`. This is not drift. `honest_state.json` is the frozen
M3F baseline; cohort growth is reconciled append-only against that baseline by
`eth_research.m3f.growable`, which proves the catalogued baseline survives as an exact hash-verified
prefix of the live chain. Both readers agree the growth is lawful.

## Registries and one-shot budgets

| registry / budget | path |
| --- | --- |
| M3A experiments | `research/m3a/experiment_registry.jsonl` |
| M3B experiments | `research/m3b/experiment_registry.jsonl` |
| M3C experiments + budget | `research/m3c/experiment_registry.jsonl`, `research/m3c/research_budget.json` |
| M3E proposals | `research/m3e/proposal_registry.jsonl` |
| M3E acceptances | `research/m3e/acceptance_registry.jsonl` |
| V2A research | `research/v2a/research_registry.jsonl` |
| V2B research + one-shot budget | `research/v2b/v2b_research_registry.jsonl`, `research/v2b/v2b_one_shot_budget.json` |
| V2C operational qualification | `governance/v2c/oq_registry.jsonl` |

**No V2F artifact of any kind exists yet**: no `research/v2f/`, no `src/eth_research/v2f/`, no V2F
document other than this one. The V2F one-shot has not been created, let alone consumed.

## Workflow inventory

Eighteen workflows. Triggers as measured:

| workflow | triggers |
| --- | --- |
| `ci.yml` | push, pull_request |
| `m2b-replay.yml`, `m3a-replay.yml`, `m3b-replay.yml`, `m3c-replay.yml`, `m3d-replay.yml`, `m3e-replay.yml`, `m3f-replay.yml`, `m4b-replay.yml` | push, pull_request |
| `v2a-replay.yml`, `v2ab-replay.yml`, `v2b-replay.yml`, `v2c-replay.yml`, `v2-fable5-replay.yml` | push, pull_request |
| `m3e-update-pr-check.yml` | pull_request |
| `m3e-prospective-update.yml` | schedule, workflow_dispatch |
| `private-release-build.yml` | workflow_dispatch |
| `release-dry-run.yml` | push, workflow_dispatch |

No workflow uses `pull_request_target`. Full per-workflow permission and pinning analysis is Agent
A's job and lands in `docs/V2_PUBLIC_REPOSITORY_THREAT_MODEL.md`; this table is the inventory only.

## Secret and credential exposure — full reachable history

Because the repository is public, HEAD is not the exposure surface; all of history is.

Method: enumerated all reachable objects (`git rev-list --objects --all`), resolved types and sizes
via `git cat-file --batch-check --batch-all-objects`, and scanned **every reachable blob** with the
committed redacting scanner `tools/scan_secrets.py`.

| measure | value |
| --- | --- |
| reachable named objects | 4374 |
| blobs scanned | 2232 |
| blobs skipped (>8 MiB) | 0 |
| findings | 4 |

All four are **secret-shaped synthetic test fixtures**, classified by inspecting structure with the
matched text masked — no value was printed, logged or recorded anywhere:

| detector | path | classification |
| --- | --- | --- |
| `pem_private_key` | `tests/test_buyer_boundary.py` | a bare dash-wrapped `BEGIN RSA PRIVATE KEY` header line, **no key material** |
| `aws_access_key_id` | `tests/test_buyer_boundary.py` | `"AKIA"` + hand-written placeholder |
| `secret_assignment` | `tests/test_buyer_boundary.py` | `api_key = 'abcd…'` placeholder |
| `pem_private_key` | `tests/test_m3e_file_policy.py` | bare PEM header with body `AAAA` |

All four are parametrised inputs to redaction/refusal tests — they exist to prove the scanner and the
file policy *catch* such shapes. The `abcd`-prefixed placeholders and the empty PEM bodies are
decisive.

**No real credential is exposed in the working tree or in reachable history. This is not a hard
stop.** At HEAD both files now assemble their fixtures at runtime, so `tools/scan_secrets.py` over
the whole tree exits 0.

This finding is the primary agent's own scan. Agent A re-derives it independently with different
detectors (GitHub/Slack/Stripe/GCP token prefixes, high-entropy scanning, dangerous file types); any
disagreement is itself a finding.

## Baseline digests

`git ls-tree -r HEAD` per prefix, sorted, SHA-256 over the joined `mode type sha\tpath` lines:

| surface | files | sha256 |
| --- | --- | --- |
| `src/` | 354 | `b197dc2db8fccd601abe4b7bd74c72891cfbacb778657f652a4c01f52995e39e` |
| `tests/` | 294 | `fd14c09667bab0f8ec79175aa747fb72b6552eac66ac07ac21bdfe386bd3e647` |
| `tools/` | 13 | `bedc39320692a4bb543d6ae94d89cb72803e1f68ef6c2b347b68ca80500dc59e` |
| `governance/` | 26 | `4d3c662d7b833a1ff95ddf32856b148f6506d377158cd2ca3146ad0ef79b6a35` |
| `research/` | 205 | `5ac3b9ff1ac4735df06ec517b1c1ba1508be476735cd23a4025fcc0e2fec13f1` |
| `release/` | 7 | `93da759b1cbffa9e94c1a02f0a0ec3794e4cc55f2e1fe1e26f71e6317009b048` |
| `docs/` | 164 | `de3aeeb656f4916ca8237f2664cd930a33e34dbc88fe97872365ebdee56ffe03` |
| `.github/workflows/` | 18 | `5dcbed9e17c5070460c539d79ae9b42c593c4c2cccc2c0abef969f303f40de10` |

Individual file digests:

| file | sha256 |
| --- | --- |
| `pyproject.toml` | `8611f0744134c6a027ae3766e04386d5fd37d0b9e622a87515d4e7d1b06d9515` |
| `uv.lock` | `cf106615a2694ce5f2c30b33e13bf385cf9cd8ef72cd102e1dfe582eaebffa64` |
| `research/m3d/prospective_manifest.json` | `a3b9b522ed60b597a38c821e15ea8b5c776edc0d128381b854ac4c39ef3c14ac` |
| `research/m3e/accepted_base.json` | `0fbae5f7abbccb93fcb21575745151f68e8b8c194e10c644654d266a3aec6925` |
| `research/m3e/acceptance_registry.jsonl` | `12e8323c204abc118666d312ccf5ea937e4c92742935a155f713031acb0efcad` |
| `research/m3e/proposal_registry.jsonl` | `067df0cb58e179d6c7750fb837dacd2b3ec5cabf2e6e4550e4abcc10f95324aa` |
| `research/m3f/honest_state.json` | `6853ccddd59d7dd104ea80448059e64667e7d0e4fd0ed6e3fbd571d6fe37c90a` |
| `research/m3f/freeze_catalog.json` | `f57fdd99aa482fee6ba6e26b6d9f373ccb08fe51fea66f6f28b39dc6f3760fe6` |
| `governance/v2/fable5_system_inventory.json` | `f9dcb70475cba2ee0cd6025158386ce50cb017f69b2d44c3a53b0aaa8f089fef` |
| `governance/v2/fable5_source_freeze.json` | `f242599943139680ad16c64df1bc3e51f667b785135a9e94b7563ae3e7caf0b6` |

## Verifier state at HEAD

All four acceptance-layer readers exit 0, and the Fable 5 governed surface verifies:

| check | exit |
| --- | --- |
| `eth_research.m3e.acceptance … check` (public entry) | 0 |
| `verify_acceptance_program` (production library call) | 0 |
| `eth_research.m3f.audit` (compatibility path) | 0 |
| `tools/m3f_independent_verify.py` (stdlib, no `eth_research`) | 0 |
| `eth_research.v2.fable5 verify` | 0 |
| `eth_research.v2.fable5 freeze-verify` | 0 |
| `tools/scan_secrets.py --repo-root .` | 0 |

## Failing tests — the honest position

**The branch is not green.** The full suite, run unpiped from an immutable disposable worktree at the
exact commit under test, failed with **14 failures**. The same tests **pass at the branch base
`f42e5b5`**, so this branch introduced every one of them.

This was not visible earlier because prior checkpoints on this branch ran *targeted* test subsets.
Targeted runs cannot establish that a branch is green, and reporting them as if they could was wrong.

Two are fixed as of `0d01b08`:

| test | classification | resolution |
| --- | --- | --- |
| `test_v2d_activation::test_tampered_accepted_evidence_refuses` | **vacuous probe** — searched for `"row_count": 3`, which the grown cohort no longer contains, so the mutation was a no-op and the test asserted that an *untampered* tree refuses | mutation now derived from the file and asserted to have changed bytes |
| `test_secret_scanner::test_whole_repo_tree_has_no_secret` | self-inflicted false positive — a literal PEM header in a fixture | fixture assembled at runtime; detector untouched |

Twelve remain, in three groups:

**Group 1 — stale pre-acceptance expectations.** These encode the world before the cohort grew 3 → 12
and before the proposal registry gained an entry:

- `test_m3d_cli::test_status_reports_the_honest_data_only_state` (`assert 12 == 3`)
- `test_m3d_firewall::test_cohort_is_immature_and_never_authorized` (`assert 12 == 3`)
- `test_m3d_quality::test_real_quality_report_has_zero_errors` (`assert 353 == 362`)
- `test_stack_freeze_table::test_proposal_registry_is_append_chain_with_no_proposal` (name says it)
- `test_m3e_review_registry::test_registry_is_deterministic_and_matches_committed`
- `test_v2d_activation::test_gate_passes_on_a_faithful_disposable_copy` (`assert base.row_count == 3`)

**Group 2 — governance collision (most serious).** Accepting the proposal changes the research tree,
which changes a `governed_state_digest` pinned by *frozen v1.1.0 release evidence*:

- `test_ga_release_artifacts::test_release_evidence_is_current`
- `test_ga_release_artifacts::test_ga_hardening_changed_no_governed_artifact`
- `test_private_release::test_check_passes_and_mutates_nothing`
- `test_private_release::test_committed_manifest_source_fields_reproduce`

Whether the frozen release evidence is rebuilt, or the acceptance is scoped so as not to disturb it,
is a governance decision about already-released artifacts. It is not a test fix and must not be
treated as one.

**Group 3 — fixture/behaviour drift:**

- `test_m3e_publisher_e2e::test_end_to_end_proposal_in_a_disposable_repo` — a fixed `as_of`
  completed-day boundary (`2026-07-22`) now *predates* the accepted last open (`2026-07-23`), which
  the clock-anomaly guard correctly refuses
- `test_m3f_redteam::test_hidden_write_workflow_trips_forever_invariant` — expected regex
  `workflow can write` did not match

None of these may be resolved by relaxing an assertion. Several of these tests exist precisely to
catch the kind of drift now occurring, and silencing them would convert a real signal into a
comfortable number.

## Preflight stop conditions — none triggered

| condition | state |
| --- | --- |
| sealed ledger unexpectedly non-empty | no — all three byte-empty |
| a sealed value has been read | no |
| unexplained strategy evaluation exists | no — every evaluation flag false |
| one-shot unexpectedly consumed | no — the V2F one-shot does not exist yet |
| working tree contains unowned changes | no — tree clean |
| credential appears exposed | no — four history hits, all synthetic fixtures |

Proceeding is authorized. The immediate blocking work is the public-repository security reset (§2)
and closing the twelve remaining failures plus unanimous auditor acceptance (§3), in that order.
No V2F selector research may begin until §3 completes.
