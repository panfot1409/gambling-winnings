"""The immutable aligned ETH/BTC research partition (V2B §15).

The joint partition is built **internally** from committed bytes — never from a caller-supplied
frame. ETH comes through the accepted firewalled loader
(:func:`eth_research.v2.partitions.load_research_train_only`, which reconstructs the research-train
from committed raw and refuses any row on/after the research cutoff); BTC comes through
:func:`eth_research.v2b.btc_dataset.load_canonical_btc_dataset` (which re-derives the canonical
series from the committed raw bundles and re-proves genesis↔audit equality). The builder aligns the
two on their exact shared daily opens, re-asserts the firewall, and recomputes every fingerprint.

Because the only input is ``repo_root``, a caller cannot substitute a fabricated BTC frame, a
hand-built ETH frame, a forged quality report, a copied manifest, a symlinked dataset, or a
same-dates-different-candles dataset: the partition is re-derived from the committed raw bytes each
time and the committed identity must reproduce byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.v2.partitions import (
    RESEARCH_TRAIN_LAST_OPEN,
    load_research_train_only,
)
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from eth_research.v2b.acquisition import RESEARCH_CUTOFF_LAST_OPEN, WINDOW_END_EXCLUSIVE
from eth_research.v2b.btc_dataset import load_canonical_btc_dataset

JOINT_PARTITION_IDENTITY_RELPATH = "research/v2b/joint_partition_identity.json"
JOINT_PARTITION_SCHEMA_VERSION = 1
ALIGNMENT_POLICY = "exact_shared_daily_opens"
EXPECTED_ROWS = 2221
_OHLCV = ("open", "high", "low", "close", "volume")

# Candidate-facing joint close columns (must match eth_research.v2b.candidates).
ETH_CLOSE = "eth_close"
BTC_CLOSE = "btc_close"


class JointPartitionError(V2ValidationError):
    """The aligned ETH/BTC partition failed an identity/alignment/firewall invariant."""


@dataclass(frozen=True, slots=True)
class JointPartition:
    """The aligned ETH/BTC panel plus its recomputed identity fingerprints."""

    panel: pd.DataFrame  # index=timestamp (UTC); eth_* and btc_* OHLCV columns
    eth_dataset_fingerprint: str
    btc_dataset_fingerprint: str
    aligned_timestamp_fingerprint: str
    eth_content_fingerprint: str
    btc_content_fingerprint: str
    combined_partition_fingerprint: str
    row_count: int
    first_open: pd.Timestamp
    last_open: pd.Timestamp

    def candidate_panel(self) -> pd.DataFrame:
        """The joint close panel the candidate families read (eth_close, btc_close)."""
        out = pd.DataFrame(index=self.panel.index)
        out[ETH_CLOSE] = self.panel["eth_close"]
        out[BTC_CLOSE] = self.panel["btc_close"]
        return out


def _instrument_fingerprint(frame: pd.DataFrame, prefix: str) -> str:
    lines = []
    for i, ts in enumerate(frame.index):
        stamp = pd.Timestamp(ts).isoformat().replace("+00:00", "Z")
        vals = ",".join(repr(float(frame[f"{prefix}_{c}"].iloc[i])) for c in _OHLCV)
        lines.append(f"{stamp},{vals}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def build_joint_partition(repo_root: str | Path) -> JointPartition:
    """Build the aligned ETH/BTC partition from committed bytes; fail closed on any drift."""
    root = Path(repo_root)
    eth = load_research_train_only(root)
    btc = load_canonical_btc_dataset(root)

    if not eth.frame.index.equals(btc.frame.index):
        raise JointPartitionError("ETH and BTC daily opens are not the exact same set")
    if len(eth.frame) != EXPECTED_ROWS:
        raise JointPartitionError(
            f"aligned partition has {len(eth.frame)} rows, expected {EXPECTED_ROWS}"
        )

    index = eth.frame.index
    # Firewall: not one aligned row on/after the research cutoff or the window end.
    if not bool((index <= RESEARCH_CUTOFF_LAST_OPEN).all()):
        raise JointPartitionError("aligned partition contains a row at/after the research cutoff")
    if not bool((index < WINDOW_END_EXCLUSIVE).all()):
        raise JointPartitionError("aligned partition contains a row at/after the window end")
    if index[-1] != pd.Timestamp(RESEARCH_TRAIN_LAST_OPEN):
        raise JointPartitionError("aligned partition last open is not the research cutoff")

    panel = pd.DataFrame(index=index)
    for col in _OHLCV:
        panel[f"eth_{col}"] = eth.frame[col].to_numpy()
        panel[f"btc_{col}"] = btc.frame[col].to_numpy()
    panel.index.name = "timestamp"

    aligned_ts_fp = sha256_bytes(
        "\n".join(pd.Timestamp(ts).isoformat().replace("+00:00", "Z") for ts in index).encode()
    )
    eth_content_fp = _instrument_fingerprint(panel, "eth")
    btc_content_fp = _instrument_fingerprint(panel, "btc")
    combined = canonical_sha256(
        {
            "eth_dataset_fingerprint": eth.content_fingerprint,
            "btc_dataset_fingerprint": btc.content_fingerprint,
            "aligned_timestamp_fingerprint": aligned_ts_fp,
            "eth_content_fingerprint": eth_content_fp,
            "btc_content_fingerprint": btc_content_fp,
        }
    )
    return JointPartition(
        panel=panel,
        eth_dataset_fingerprint=eth.content_fingerprint,
        btc_dataset_fingerprint=btc.content_fingerprint,
        aligned_timestamp_fingerprint=aligned_ts_fp,
        eth_content_fingerprint=eth_content_fp,
        btc_content_fingerprint=btc_content_fp,
        combined_partition_fingerprint=combined,
        row_count=len(index),
        first_open=index[0],
        last_open=index[-1],
    )


def build_partition_identity(repo_root: str | Path) -> dict[str, Any]:
    """The frozen, byte-reproducible aligned-partition identity."""
    jp = build_joint_partition(repo_root)
    return {
        "schema_version": JOINT_PARTITION_SCHEMA_VERSION,
        "kind": "eth_btc_joint_partition_identity",
        "instruments": ["BTC-USD", "ETH-USD"],
        "venues": ["coinbase-exchange"],
        "interval_seconds": 86_400,
        "base_currency": "USD",
        "alignment_policy": ALIGNMENT_POLICY,
        "research_cutoff_last_open": RESEARCH_CUTOFF_LAST_OPEN.isoformat().replace("+00:00", "Z"),
        "row_count": jp.row_count,
        "first_open": pd.Timestamp(jp.first_open).isoformat().replace("+00:00", "Z"),
        "last_open": pd.Timestamp(jp.last_open).isoformat().replace("+00:00", "Z"),
        "no_row_at_or_after_cutoff": True,
        "eth_dataset_fingerprint": jp.eth_dataset_fingerprint,
        "btc_dataset_fingerprint": jp.btc_dataset_fingerprint,
        "aligned_timestamp_fingerprint": jp.aligned_timestamp_fingerprint,
        "eth_content_fingerprint": jp.eth_content_fingerprint,
        "btc_content_fingerprint": jp.btc_content_fingerprint,
        "combined_partition_fingerprint": jp.combined_partition_fingerprint,
    }


def render_partition_identity_bytes(repo_root: str | Path) -> bytes:
    return canonical_json_bytes(build_partition_identity(repo_root))


def verify_joint_partition(repo_root: str | Path) -> None:
    """The committed joint-partition identity reproduces byte-for-byte from committed bytes."""
    root = Path(repo_root)
    committed = (root / JOINT_PARTITION_IDENTITY_RELPATH).read_bytes()
    if committed != render_partition_identity_bytes(root):
        raise JointPartitionError(
            "committed joint_partition_identity.json does not reproduce from the committed datasets"
        )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B aligned ETH/BTC partition (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.write:
        (root / JOINT_PARTITION_IDENTITY_RELPATH).write_bytes(render_partition_identity_bytes(root))
        print(f"wrote {JOINT_PARTITION_IDENTITY_RELPATH}")
        return 0
    try:
        verify_joint_partition(root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
