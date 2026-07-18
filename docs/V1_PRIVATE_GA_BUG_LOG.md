# V1 private-GA pre-merge red-team bug log (§21)

Three independent, read-only red teams audited the private-GA tree at `release/v1.1.0-private-ga`
before the code freeze:

- **Red team A** — privacy / leakage / distribution.
- **Red team B** — reproducibility / provenance / consumer.
- **Red team C** — workflow / token / governance.

**No Class A (public exposure / secret leak) and no Class D (governed drift) finding.** All three
independently confirmed the criticals hold: the built wheel/sdist/payload contain only
`src/eth_research/**` + `pyproject.toml` + `README.md` (+ the benign `.gitignore`/`PKG-INFO`/
dist-info) with no `research/`, data, or ledger member; the payload is byte-deterministic and equals
the committed manifest; the governed-state digest reproduces `b2077eaf…`; the three sealed ledgers
stay byte-empty; version is `1.1.0`; no `LICENSE`; the private-release workflow is least-privilege.

Six Class B/C findings were reported and every one was fixed failing-test-first. Each fix keeps the
package version at `1.1.0`, changes no `research/` artifact, and leaves the sealed ledgers byte-empty.

## Findings and dispositions

| ID | Class | Summary | Fix |
| --- | --- | --- | --- |
| C-1 | C | The public-publication kill switch and both workflow scanners had no pattern for `uv publish` (or `poetry`/`flit`/`hatch publish`) — a real upload path given the toolchain standardizes on `uv`. | Added `uv_publish` and `build_backend_publish` vectors to `FORBIDDEN_VECTORS` in `tests/test_public_publication_killswitch.py`; extended the planted-vector test. |
| C-2 | C | The kill switch scanned `.github/workflows`, `src/eth_research`, and `tools` but **not** `.github/scripts/`, which is live auto-triggered CI surface (`m3a-replay.yml` runs `.github/scripts/verify_m3a_registry.py`). | `_scanned_files()` now also walks `.github/scripts/**` (every file, not just `*.py`); the coverage guard asserts `verify_m3a_registry.py` is scanned. |
| A-1 | C | `tools/scan_secrets.py` missed modern token formats: GitHub fine-grained PATs (`github_pat_`), GitLab (`glpat-`), Google (`AIza`), Stripe (`sk_live_`/`rk_live_`), and Slack app tokens (`xapp-`). Latent detection weakness; none present in-tree. | Added five fragment-assembled detectors (keeping the scanner self-non-matching) + a planted positive test per class; re-verified the tree and a freshly built wheel/sdist/payload scan clean. |
| A-2 | C | `docs/V1_LICENSE_DECISION.md` still carried an actionable step-by-step runbook to enable public PyPI publication (add a LICENSE, an OSI classifier, "re-run `publish-release.yml`"). Doc-hygiene: the automated gates still fail closed, but this is residual actionable public-publication instruction the milestone forbids. | Neutralized the runbook section (mirroring `V1_PUBLICATION_PIPELINE.md`); no actionable public-publication steps remain in the file. |
| B-1 | B | `docs/V1_PRIVATE_REPRODUCIBILITY.md` claimed the wheel and sdist are a pure function of "exactly three inputs" and that "every dotfile [is] excluded from the sdist". Hatchling always ships the repo-root `.gitignore` in the sdist (acknowledged at `pyproject.toml`), so the sdist is a function of **four** inputs — reproduced (appending to `.gitignore` changes the sdist hash). | Corrected the doc to name the root `.gitignore` as the sdist's fourth input and drop the dotfile-exclusion overclaim; added a build-free doc-honesty test and a `@slow` test proving `.gitignore` rides in the sdist. |
| B-2 | C | `private-release-build.yml` ran the *old* generic `test_consumer_e2e.py` (guarded by `if [ -f … ]; else skipping`), not the §9 `test_private_consumer_matrix.py`; its determinism step only checked build self-consistency, never equality to the committed manifest; and both the matrix and the reproduce-from-build guard are `@slow`, one `-m 'not slow'` away from silent skip. | Rewrote the release workflow: install CPython 3.13 so the matrix's 3.13 cells run; the determinism step now also runs the committed-manifest reproduce-from-build guard and fails if it is skipped/deselected; a fail-closed step runs `test_private_consumer_matrix.py` + the installed-wheel E2Es and fails on any skip/deselect or a missing matrix file. |

## Acknowledged minor notes (no code change)

- **`scan_distribution.py` `_FORBIDDEN_SUFFIXES` omits `.json`** (raw market data is stored as
  `.json`). Red team A confirmed this is **not an actual miss**: the distribution scanner's *positive*
  member allowlist rejects any `.json` in the wheel/sdist as an unexpected member, and the built
  artifacts carry no `.json`. Left as-is to keep the belt-and-suspenders suffix list from risking a
  false positive; the positive allowlist is the authoritative control.
- **`test_private_consumer_matrix.py` `repo_on_path` hardcodes `…/gambling-winnings/src`** as a
  *secondary* guard. The primary `"site-packages" in package_file` assertion is robust and
  directory-name independent, so there is no functional gap.
- **Cross-cell `result_id` equality (3.12.3 vs 3.13)** is not asserted in the matrix; both red teams
  observed the ids are empirically identical. Each cell already asserts its own determinism; the
  release workflow now runs the whole matrix on both runtimes.
- **Repository visibility is an external control** not verifiable from the filesystem. The private-
  release workflow refuses to run unless `github.event.repository.private == true`; confirming the
  GitHub visibility setting itself remains an out-of-band owner check.

## Re-audit

After the fixes, the three red teams were re-run against the corrected tree; the full test suite is
green on the authoritative runtime. See `docs/V1_PRIVATE_GA_ACCEPTANCE_AUDIT.md` for the acceptance
verdict.
