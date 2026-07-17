# Security policy

## Posture

`eth-research` is a **research-only, offline** toolkit. By design it has:

- **no** network client, exchange/broker connectivity, or API authentication;
- **no** wallet, key handling, signing, or order routing;
- **no** dynamic code loading (`eval`/`exec`/plugin import) in the runtime package;
- **no** leverage, margin, shorting, or derivatives; long-only, cash-safe accounting only.

The runtime depends only on `numpy`, `pandas`, and `pyarrow`. This narrow surface is the project's
primary security property, and it is enforced by tests (an import-closure firewall and a distribution
scanner). Please help keep it that way.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.1.x | ✅ |
| 1.0.x | ✅ |
| < 1.0 | ❌ (internal research milestones) |

## Reporting a vulnerability

Please report suspected vulnerabilities **privately**, not in a public issue:

- Use GitHub's **[private security advisories](https://github.com/panfot1409/gambling-winnings/security/advisories/new)**
  ("Report a vulnerability") for this repository.

Include: affected version/commit, a description, and a minimal reproduction if possible. Because the
package touches no network, funds, or credentials, the most valuable reports concern the integrity of
the offline pipeline — for example a way to smuggle private data into a built distribution, defeat the
import firewall, forge a result/receipt that verifies, or make a deterministic artifact
non-reproducible.

Please allow a reasonable window for a fix before any public disclosure. There is no bug-bounty
program.

## Out of scope

This project provides **no trading, investment, or financial advice** and makes **no alpha claim**.
"My backtest was unprofitable" or "the strategy lost money on my data" is not a security issue.
