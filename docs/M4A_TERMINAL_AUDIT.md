# M4A terminal acceptance audit

An independent, post-freeze read-through of the Milestone 4A **Offline Research Platform 1.0
release candidate**, stacked on the accepted M3F head (`e231359`). It records the terminal
state against the acceptance criteria and confirms the hard-stop boundaries held. This audit
is descriptive; it changes no source and no accepted artifact.

## Scope

M4A turns the accepted internal research stack (M2B–M3F) into a trustworthy, installable,
private-data-safe **v1.0.0** offline research platform: a small strictly-typed public API
(`eth_research.api`), one offline CLI (`eth-research`), strict versioned config / result /
run-receipt schemas, a closed public error taxonomy, a deterministic synthetic quickstart, a
private-data-safe wheel + sdist with an inclusion allowlist and a scanner, a reproducible
double build, an installed-wheel consumer E2E, a public strategy protocol (no plugin loader),
a full docs set with a generated CLI reference, and a read-only release-candidate CI. It is
stacked as a **draft** PR on the M3F branch; it does not retarget or modify any earlier layer.

## Terminal acceptance criteria — verified

| Criterion | State |
| --- | --- |
| Full local battery green (`ruff` / `ruff format` / `mypy` / `pytest`) | ✅ green |
| Version identifies as `1.0.0` | ✅ (`test_version.py`, `release_candidate_state.json`) |
| Public API + CLI + release snapshots `--check` clean | ✅ `public_api` / `cli_reference` / `release` |
| Both engines compatibility-identical to the accepted engines | ✅ metrics delegated verbatim (Auditor A: Class A nothing) |
| Wheel + sdist double-build byte-identical (Linux) | ✅ `test_packaging.py::test_double_build_is_byte_identical` |
| Private-data distribution scan clean (pure-Python allowlist) | ✅ `test_packaging.py`, `tools/scan_distribution.py` |
| Installed-wheel consumer E2E green, out-of-tree | ✅ `test_consumer_e2e.py` |
| Distribution manifest matches the built wheel, byte for byte | ✅ `test_m4a_release.py` |
| Accepted M2B–M3F artifacts byte-unchanged | ✅ empty diff vs `e231359` across `research/**` (m2b…m3f), `data/**`, M2B/M3 source |
| Three sealed ledgers byte-empty | ✅ each 0 bytes / empty-string sha256 |
| Frozen M3F acceptance audit still verifies | ✅ `python -m eth_research.m3f.audit --repo-root . --deep` |
| Governance states unchanged (M3C rejected · M3D at its 3/365 authorized cap · M3E ready-but-inactive, 0 proposals) | ✅ certified by the passing frozen M3F audit |
| Offline: no network / exchange / wallet / order-routing capability | ✅ firewall test + real `doctor` offline check |
| New governed root `research/m4a/` self-verifying, out of the frozen freeze table | ✅ `test_stack_freeze_table.py`, `test_m3f_acceptance_hardening.py` |

## Independent pre-freeze red team

Three independent auditors (A: API + numerical, B: packaging + supply-chain, C: CLI +
security + publication) reviewed the RC read-only. **No Class D finding** (accepted-artifact /
sealed-ledger / network touch) was reported, and no accepted-financial-artifact change was
required, so no hard stop was triggered. Every reproduced Class B/C finding was fixed
failing-test-first, or documented as an honest boundary. Full disposition:
[M4A_FINDINGS.md](M4A_FINDINGS.md); reproduced defects and fixes:
[M4A_BUG_LOG.md](M4A_BUG_LOG.md). Headline fixes: symlink confinement of the dataset read and
the output write (F1/F2), a governed-path guard on the operator `--output` (F3), a
pure-Python distribution allowlist (B1), and a receipt `run_id` that now binds the full run
identity including the context fingerprint, the split, and the dataset manifest digest
(A1/A3).

## Hard-stop boundaries — respected

Nothing in M4A merged, undrafted, retargeted, tagged, released, or published any PR; published
to any registry; deleted a branch; rebased, amended, or force-pushed shared history; changed a
repository setting or secret; appended a sealed ledger; added exchange auth, wallets, signing,
order routing, live/paper trading, leverage, shorting, margin, or derivatives; added a general
network client to the package; added an optimizer, grid/Bayesian/genetic search, or any ML;
added a new research strategy; packaged a raw Coinbase byte or a recovery capsule; mutated
M3C/M3D/M3E state; accessed the development gate or the final holdout; or started M4B. No
accepted financial artifact was changed.

## Absolute final stop

The release candidate is code-complete, hardened, and green. It is published only as a
**draft** stacked pull request whose base is the M3F branch
(`claude/m3f-independent-verification-recovery`); it is left unmerged, unretargeted, untagged,
unreleased, and unpublished, and M3C / M3D / M3E and the sealed ledgers are left untouched.
Promotion of this release candidate — a license, a public/PyPI release, or a merge — is a
human decision outside this milestone.

## Verdict

**Accepted as a v1.0.0 release candidate.** The offline research platform is installable,
private-data-safe, reproducible, and tamper-evident; it delegates every financial number to
the accepted engines without reimplementation; and it leaves the accepted M2B–M3F stack and
all sealed governance state byte-for-byte intact.
