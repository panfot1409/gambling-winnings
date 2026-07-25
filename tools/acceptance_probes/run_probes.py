"""Execute the probe matrix and write the machine-readable truth table."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_lib import SCRATCH, execute, require_clean_repo
from probe_matrix import PROBES

OUT = SCRATCH / "truth_table_raw.json"


def main() -> int:
    only = {a for a in sys.argv[1:] if not a.startswith("-")}
    head = require_clean_repo()
    print(f"head under test: {head}")
    SCRATCH.mkdir(parents=True, exist_ok=True)

    rows = []
    if OUT.exists() and "--fresh" not in sys.argv:
        rows = json.loads(OUT.read_text())["rows"]
    done = {r["probe_id"] for r in rows}

    for probe in PROBES:
        if only and probe.probe_id not in only:
            continue
        if probe.probe_id in done and not only:
            continue
        t0 = time.monotonic()
        row = execute(probe)
        row["seconds"] = round(time.monotonic() - t0, 1)
        rows = [r for r in rows if r["probe_id"] != probe.probe_id] + [row]
        order = {p.probe_id: i for i, p in enumerate(PROBES)}
        rows.sort(key=lambda r: order.get(r["probe_id"], 999))
        OUT.write_text(json.dumps({"head": head, "rows": rows}, indent=2) + "\n")
        readers = row.get("readers", {})
        flags = " ".join(f"{k[:4]}={'P' if v['exit'] == 0 else 'R'}" for k, v in readers.items())
        print(
            f"{probe.probe_id:9} {row.get('outcome', 'SETUP_ERROR'):24} {flags}  "
            f"guard={'Y' if row.get('reached_intended_guard') else 'n'} "
            f"({row['seconds']}s)"
        )
        if row.get("setup_error"):
            print(f"           SETUP ERROR: {row['setup_error'][:300]}")
    print(f"\nwrote {OUT}  ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
