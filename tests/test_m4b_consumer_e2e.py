"""Installed-wheel M4B consumer end-to-end: the portfolio simulator works from an installed wheel.

Builds the wheel, installs it non-editable into a throwaway virtual environment, and drives the
``eth_research.portfolio`` public API from a working directory outside the repository — proving the
multi-asset simulator imports, runs the synthetic reference universe end to end, builds a result
that passes the full-graph verifier, and is deterministic, all as an installed package with the
repository source off ``sys.path``. This is the M4B v1.1 consumer that complements the accepted M4A
v1.0 consumer (``test_consumer_e2e.py``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Driven in the *installed* interpreter, out of tree: build the reference universe, run it, build
# and verify the result twice, and report the identity and a determinism check as one JSON line.
_DRIVER = """
import json
import sys

from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import build_reference_universe, reference_protocol
from eth_research.portfolio.result import build_portfolio_result, verify_portfolio_result

import eth_research

_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


def _build():
    reference = build_reference_universe()
    run = run_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    ppy = _SECONDS_PER_YEAR / reference.universe_spec.bar_interval_seconds
    metrics = compute_portfolio_metrics(run, periods_per_year=ppy)
    result = build_portfolio_result(run, metrics, reference.universe_spec)
    verify_portfolio_result(result, reference.universe_spec, run)
    return result


first = _build()
second = _build()
print(
    json.dumps(
        {
            "package_file": eth_research.__file__,
            "repo_on_path": any(
                str(p).endswith("gambling-winnings/src") for p in sys.path
            ),
            "result_id": first.result_id,
            "deterministic": first.result_id == second.result_id
            and first.canonical() == second.canonical(),
            "base_currency": first.base_currency,
            "instruments": len(first.per_asset_contribution),
        }
    )
)
"""


@pytest.fixture(scope="module")
def portfolio_consumer(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    dist = tmp_path_factory.mktemp("m4b_dist")
    venv = tmp_path_factory.mktemp("m4b_venv")
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dist)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
        wheel = next(dist.glob("*.whl"))
        subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True, text=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), str(wheel)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available for the consumer E2E")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"consumer install unavailable (offline?): {exc.stderr}")
    workdir = tmp_path_factory.mktemp("m4b_workdir")  # outside the repo
    return venv, workdir


def test_installed_portfolio_runs_verifies_and_is_deterministic(
    portfolio_consumer: tuple[Path, Path],
) -> None:
    venv, workdir = portfolio_consumer
    proc = subprocess.run(
        [str(venv / "bin" / "python"), "-c", _DRIVER],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert "site-packages" in payload["package_file"]  # the installed wheel, not the repo tree
    assert payload["repo_on_path"] is False
    assert payload["deterministic"] is True
    assert len(payload["result_id"]) == 64
    assert payload["base_currency"] == "USD"
    assert payload["instruments"] == 3  # the reference universe's three instruments
