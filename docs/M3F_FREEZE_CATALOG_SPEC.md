# Milestone 3F — freeze catalog specification

The freeze catalog (`research/m3f/freeze_catalog.json`) is the byte-level record
that binds the accepted M2B–M3E research stack to its source-freeze commit. This
document specifies how it is built, what it contains, and exactly what its
verification proves.

## Purpose

The catalog answers one question deterministically: *does every tracked governed
artifact still hold the exact bytes it held at the source-freeze commit?* It is
generated once at registration (R) and verified on every replay and in CI.

## Generation

`catalog.build_catalog(repo_root, *, source_freeze_sha, accepted_main_sha,
package_version)` derives the catalog entirely from git-blob bytes at the
source-freeze commit `E`:

1. Enumerate every tracked file under `research/` (`git ls-files`).
2. **Exclude the whole M3F verification layer** (`research/m3f/…`). It is created
   at registration, *after* `E`, and each of its artifacts is self-verifying;
   cataloguing a file that does not exist at the freeze commit would be an E-vs-R
   circularity. The accepted M2B–M3E stack is fully catalogued.
3. For each remaining file, read its blob bytes at `E` and record `path`,
   `sha256`, `byte_length`, `milestone` (by path prefix), `role`, `market_bytes`,
   and `capsule_permitted`.
4. Record the source tree fingerprint (`git ls-tree -r <E> src`), the accepted
   `main` SHA and its tree SHA, the three sealed ledgers (byte-empty), and the
   expected governance state derived from the accepted decision, base, and
   registry at `E`.

The catalog is serialized as canonical JSON (sorted keys, two-space indent,
trailing newline, finite-only, artifacts sorted by path), so it reproduces
byte-for-byte.

## Schema (top level)

| Field | Meaning |
|---|---|
| `schema_version` | catalog schema version (1) |
| `catalog_algorithm` | hash algorithm identifier (`sha256`) |
| `accepted_main_sha` / `accepted_main_tree_sha` | the accepted merge commit and its tree |
| `package_version` | M3F package version at freeze |
| `source_freeze_sha` | commit `E` whose blob bytes are catalogued |
| `source_tree_fingerprint` | SHA-256 over `git ls-tree -r <E> src` |
| `canonical_json_contract` | `utf8;sorted_keys;indent2;trailing_newline;finite_only` |
| `governed_root` | `research` |
| `artifact_count` / `artifacts[]` | catalogued files (path, sha256, byte_length, milestone, role, market_bytes, capsule_permitted) |
| `ledgers{}` | the three sealed ledgers, each recorded byte-empty |
| `expected_repository_state{}` | m3c outcome, m3d rows/maturity/authorization, m3e proposal count, sealed-ledger flag |
| `excluded_paths[]` | `data/`, `reports/`, `.venv/` |

The catalog does **not** catalog itself (self-hash circularity) nor any other
`research/m3f/` artifact.

## Verification

`catalog.verify_catalog(repo_root)` returns a result that fails closed on any of:

1. **canonical bytes** — the committed catalog is not canonical JSON, or the schema
   version is wrong.
2. **artifact present + hash + length** — a catalogued file is missing, or its
   working-tree bytes do not match the recorded SHA-256 / length.
3. **vocabulary** — an artifact's `milestone` or `role` is outside the fixed set.
4. **anti-orphan** — every tracked governed file *outside* `research/m3f/` is
   catalogued (no uncatalogued "stowaway"), and every catalogued path still exists
   (no stale entry).
5. **sealed ledgers byte-empty** — each of the three ledgers is length 0 with the
   empty-file digest.
6. **expected governance state** — the recorded governance summary matches the live
   accepted decision, base, and registry.

## What verification proves — and does not

**Proves:** the catalogued accepted artifacts are byte-identical to the frozen
source, no governed accepted file was added or removed unnoticed, the sealed
ledgers are empty, and the recorded governance summary is truthful.

**Does not prove:** that the recorded hashes themselves were not rewritten in the
same accepted commit (that is caught by human review and by the independent
verifier's separate re-hash), nor anything about the `research/m3f/` layer, which
is covered instead by its own reproduction verifiers (honest state, inventories,
capsule manifest, recovery drill) in `audit.verify_repository_freeze`.

## Coverage guarantee

The mutation matrix (`tests/test_m3f_mutation.py`) mutates each committed
artifact — accepted and M3F alike — against a registered clone and asserts the
responsible verifier detects it. Together with the catalog's anti-orphan
enumeration, this guarantees that no governed artifact is left uncovered by *some*
fail-closed check.
