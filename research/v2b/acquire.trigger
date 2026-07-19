{
  "attempt_id": "coinbase-btc-usd-research-genesis-001",
  "retry": 1,
  "note": "Transient push-sentinel that bootstraps the one-shot v2b-acquire.yml workflow. Changing this file's bytes and pushing to claude/v2b-cross-asset-research-reset triggers exactly one BTC-USD acquisition for the whitelisted attempt_id. The retry counter re-triggers after a workflow fix (the bot-commit scope check now uses --untracked-files=all). This sentinel and the workflow are removed after the genesis + audit acquisitions are verified (V2B section 13)."
}
