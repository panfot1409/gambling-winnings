# V1 private distribution

`eth-research` v1.1.0 is distributed **privately** to authorized collaborators of the private
repository `panfot1409/gambling-winnings`. It is **not** open source and is **not** published to any
public index or registry.

## What "private distribution" means here — and what it does not

These are distinct concepts and this document does not conflate them:

- **Source availability** — authorized collaborators can read the private repository source. Repository
  read access is *not* a public redistribution grant.
- **Private installation** — authorized collaborators can install v1.1.0 via the two channels below.
- **Public publication** — *not done.* No PyPI/TestPyPI, no public GitHub Release, no public registry.
- **Legal licensing** — *not decided here.* No `LICENSE` is declared; legal permissions remain an
  owner/legal decision. Project metadata authorizes no public redistribution.
- **Cryptographic signing** — *not claimed.* Artifacts are hash-bound (SHA-256), not signed.
- **Hash-bound reproducibility** — the payload is byte-deterministic on the authoritative runner; the
  private source commit is the canonical rebuild anchor.

## Authorized channels

### Channel A — immutable private Git commit (canonical)

Install pinned to the **full 40-hex commit SHA** of the final private-GA merge commit, over
authenticated SSH:

```
pip install "eth-research @ git+ssh://git@github.com/panfot1409/gambling-winnings.git@<FULL_SHA>"
```

- Requires SSH/repository authorization (private repo).
- A branch name or `main` is **not** an acceptable reproducibility pin — only the full commit SHA is.
- Third-party dependencies resolve from the caller's configured indexes.
- No public `eth-research` package is involved.

### Channel B — private wheel payload (convenience)

1. Download the access-controlled private payload artifact (`eth-research-1.1.0-private-payload.tar`)
   from the private repository's Actions run.
2. Verify the payload SHA-256 against the value in the run's receipt / this repo's registered manifest.
3. Verify `SHA256SUMS` for every member.
4. Unpack safely into a scratch directory.
5. Create a clean virtual environment.
6. Install the approved pinned dependencies (`numpy`, `pandas`, `pyarrow` at the locked versions).
7. Install the project wheel with `--no-deps` (proves the project artifact needs no index).
8. Run `eth-research doctor` / `version`, import the public API, and exercise the CLI.

The wheel is **not** standalone: it declares `numpy`/`pandas`/`pyarrow` at runtime and does not vendor
them. No dependency wheelhouse is provided (third-party redistribution/licensing is out of scope).

## Forbidden

No PyPI/TestPyPI upload, no pending publisher/OIDC/API token, no `twine`, no public registry, no public
GitHub Release, no open-source claim, no license classifier, no governed research data / raw market
data / ledger in any distributed artifact.
