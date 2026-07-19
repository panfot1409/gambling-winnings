"""Read-only operator CLIs for a shadow run: verify a journal chain and summarize it.

These commands only *read* committed shadow artifacts — a journal (JSONL) and an optional checkpoint
(JSON) — and re-verify their integrity. They never run a strategy, write a file, or touch a network:
they are the tools an operator or a buyer's reviewer uses to confirm that a recorded shadow run is
internally consistent (chain intact, checkpoint bound to the journal head).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from eth_research.shadow.checkpoint import load_checkpoint, recover
from eth_research.shadow.journal import RUN_COMPLETED, ShadowJournal


def _verify(args: argparse.Namespace) -> int:
    journal = ShadowJournal.parse(Path(args.journal).read_bytes())
    print(f"journal: {len(journal.events)} events, head {journal.head_hash}")
    if args.checkpoint:
        checkpoint = load_checkpoint(args.checkpoint)
        recover(checkpoint, journal)
        print(
            f"checkpoint OK: mode={checkpoint.mode} bars={checkpoint.bars_processed} "
            f"kill_tripped={checkpoint.kill_tripped} bound to journal head"
        )
    print("verify: OK")
    return 0


def _summary(args: argparse.Namespace) -> int:
    journal = ShadowJournal.parse(Path(args.journal).read_bytes())
    counts = Counter(event.event_type for event in journal.events)
    for event_type in sorted(counts):
        print(f"  {event_type}: {counts[event_type]}")
    completed = [e for e in journal.events if e.event_type == RUN_COMPLETED]
    if completed:
        payload = completed[-1].payload
        print(
            f"terminal: bars={payload.get('bars_processed')} "
            f"kill_tripped={payload.get('kill_tripped')} final_equity={payload.get('final_equity')}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eth-research-shadow", description="Read-only shadow-run inspection."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser(
        "verify", help="Verify a journal chain (+ optional checkpoint binding)."
    )
    verify.add_argument("--journal", required=True, help="Path to a shadow journal (JSONL).")
    verify.add_argument("--checkpoint", help="Optional path to a checkpoint to bind-check.")
    verify.set_defaults(func=_verify)

    summary = sub.add_parser("summary", help="Summarize a journal's events and terminal state.")
    summary.add_argument("--journal", required=True, help="Path to a shadow journal (JSONL).")
    summary.set_defaults(func=_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
