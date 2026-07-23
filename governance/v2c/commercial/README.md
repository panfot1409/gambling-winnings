# V2C private commercial-truth pack

Four **private**, data-only evidence artifacts for the V2C milestone (candidate-free; no strategy is
evaluated). Each is a deterministic canonical-JSON serialization of a fixed, fingerprint-pinned model
in `eth_research.v2c.commercial`, and reproduces byte-for-byte via
`eth_research.v2c.commercial.evidence.check`.

This directory lives under `governance/v2c/` -- deliberately outside the frozen `research/` and
`release/` roots pinned by the V2A-V2B freeze table -- so V2C adds evidence without touching the
frozen stack.

| Artifact | Section | What it is |
| --- | --- | --- |
| `deployment_blueprint.json` | 28 | The **inactive** offline-operations deployment blueprint. It activates nothing, opens no network egress, routes no orders, and lists every activation precondition as an unmet external human gate. |
| `sbom.cdx.json` | 29 | The **private** CycloneDX 1.5 SBOM for the V2C development distribution (`eth-research 2.0.0.dev2`), derived deterministically from `uv.lock`. Classified private; no public-distribution claim. |
| `ip_dossier.json` | 30 | A **catalog** of IP categories (not disclosure). Every category is private and not publicly disclosed; it carries the honest reverse-engineering exposure statement. |
| `commercial_options.json` | 31 | The honest commercial-options record. `sell_ready` is `false` (derived from the constitution's `not_sell_ready` posture); every path is unavailable now and gated on external human decisions. |

## Honest posture

Nothing here is for sale and nothing is published. The repository is private; the programme is
`not_sell_ready`; the deployment blueprint is inactive. The only thing offerable today is the
redacted evaluation surface, for diligence and not as a sale. Process isolation and redaction do not
prove the core IP cannot be reverse engineered.
