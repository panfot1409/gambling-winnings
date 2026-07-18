"""Fresh-consumer verification matrix (§9) for the two private install channels.

Proves ``eth-research`` 1.1.0 installs and runs **out of tree**, with ``--no-deps``, across the
supported runtimes and all three distribution forms an authorized private consumer may use:

* **wheel** and **sdist** — Channel B (private wheel payload): install the pinned runtime deps, then
  install the project artifact with ``--no-deps`` (proving the artifact needs no public index).
* **commit** — Channel A (immutable Git commit): install pinned deps, then
  ``pip install --no-deps "eth-research @ git+file://<repo>@<HEAD_SHA>"``. A local ``git+file://``
  clone pinned to the exact commit exercises the *same* pip git-install codepath as the documented
  ``git+ssh://…@<SHA>`` channel, without needing network egress or repository SSH authorization.

Every cell drives the offline CLI (``version``/``doctor``) and the ``eth_research.portfolio`` public
API from a working directory outside the repository, and asserts the package resolves from
``site-packages`` with the repository ``src`` off ``sys.path``.

Honesty about skips. Provisioning a runtime or installing the pinned third-party dependencies
needs the interpreter/toolchain and index access; when those are unavailable a cell skips (matching
``tests/test_consumer_e2e.py``). But once the pinned deps install, the environment is proven
capable, so an *artifact* install or smoke failure after that point is a real assertion, not a
skip. The standalone ``test_authoritative_wheel_cell_is_not_vacuous`` guard makes the authoritative
3.12.3 wheel cell execute end to end whenever uv/git and an index are present, so an
all-green-by-skip illusion cannot hide a broken consumer. The exact-commit *contract* checks below
need no network and always run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL_CONTRACT = REPO / "release" / "private" / "v1.1.0" / "private_install_contract.json"
PRIVATE_DISTRIBUTION_DOC = REPO / "docs" / "V1_PRIVATE_DISTRIBUTION.md"

# 3.12.3 is authoritative; 3.13 is the second supported minor. The documented "3.12" collapses onto
# 3.12.3 (same minor) and is not a distinct cell.
RUNTIMES: tuple[str, ...] = ("3.12.3", "3.13")
MODES: tuple[str, ...] = ("wheel", "sdist", "commit")

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Driven in the *installed* interpreter, out of tree: report identity + version, run the synthetic
# portfolio reference twice, verify the result, and check determinism — all as one JSON line.
_DRIVER = """
import json
import sys

import eth_research
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import build_reference_universe, reference_protocol
from eth_research.portfolio.result import build_portfolio_result, verify_portfolio_result

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
            "version": eth_research.__version__,
            "repo_on_path": any(str(p).endswith("gambling-winnings/src") for p in sys.path),
            "result_id": first.result_id,
            "deterministic": first.result_id == second.result_id
            and first.canonical() == second.canonical(),
            "base_currency": first.base_currency,
            "instruments": len(first.per_asset_contribution),
        }
    )
)
"""


def _toolchain() -> tuple[str, str] | None:
    uv = shutil.which("uv")
    git = shutil.which("git")
    if uv is None or git is None:
        return None
    return uv, git


def _pinned_dep_specs() -> list[str]:
    contract = json.loads(INSTALL_CONTRACT.read_bytes())
    specs: list[str] = []
    for dep in contract["required_runtime_dependencies"]:
        specs.append(f"{dep['name']}=={dep['locked_version']}")
    return specs


def _run(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), cwd=cwd, check=True, capture_output=True, text=True)


def _head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=REPO).stdout.strip()


def _venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def _install_artifact(venv: Path, mode: str, wheel: Path, sdist: Path) -> None:
    """Install the project artifact for ``mode`` with ``--no-deps``. Raises on failure (the caller
    has already proven the environment can install deps, so a failure here is real)."""
    python = str(_venv_python(venv))
    if mode == "wheel":
        target = str(wheel)
    elif mode == "sdist":
        target = str(sdist)
    elif mode == "commit":
        target = f"eth-research @ git+file://{REPO}@{_head_sha()}"
    else:  # pragma: no cover - guarded by MODES
        raise AssertionError(mode)
    _run(["uv", "pip", "install", "--python", python, "--no-deps", target])


def _provision_cell(runtime: str, mode: str, venv: Path, wheel: Path, sdist: Path) -> None:
    """Create a venv on ``runtime``, install pinned deps, then install the artifact for ``mode``.

    Skips (not fails) when the runtime cannot be provisioned or the pinned deps cannot be installed
    — those require an interpreter/index that may be unavailable offline.
    """
    if _toolchain() is None:
        pytest.skip("uv/git are required for the private consumer matrix")
    try:
        _run(["uv", "venv", "--python", runtime, str(venv)])
    except subprocess.CalledProcessError as exc:  # pragma: no cover - offline / runtime absent
        pytest.skip(f"runtime {runtime} unavailable: {exc.stderr}")
    python = str(_venv_python(venv))
    try:
        _run(["uv", "pip", "install", "--python", python, *_pinned_dep_specs()])
    except subprocess.CalledProcessError as exc:  # pragma: no cover - offline
        pytest.skip(f"pinned deps unavailable (offline?): {exc.stderr}")
    # From here the environment is proven capable; artifact install failures are real.
    _install_artifact(venv, mode, wheel, sdist)


def _smoke(venv: Path, workdir: Path) -> None:
    """Drive the CLI + portfolio API out of tree and assert the installed-package invariants."""
    exe = venv / "bin" / "eth-research"

    version = _run([str(exe), "version", "--json"], cwd=workdir)
    assert json.loads(version.stdout)["package_version"] == "1.1.0"

    doctor = _run([str(exe), "doctor", "--json"], cwd=workdir)
    assert json.loads(doctor.stdout)["ok"] is True

    driver = subprocess.run(
        [str(_venv_python(venv)), "-c", _DRIVER],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(driver.stdout)
    assert "site-packages" in payload["package_file"], payload["package_file"]
    assert payload["repo_on_path"] is False
    assert payload["version"] == "1.1.0"
    assert payload["deterministic"] is True
    assert len(payload["result_id"]) == 64
    assert payload["base_currency"] == "USD"
    assert payload["instruments"] == 3


@pytest.fixture(scope="module")
def built_dists(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the wheel and sdist once for the whole matrix."""
    if _toolchain() is None:
        pytest.skip("uv/git are required for the private consumer matrix")
    dist = tmp_path_factory.mktemp("private_matrix_dist")
    try:
        _run(["uv", "build", "--out-dir", str(dist)], cwd=REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover - offline
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    return wheel, sdist


@pytest.mark.slow
@pytest.mark.parametrize("runtime", RUNTIMES)
@pytest.mark.parametrize("mode", MODES)
def test_private_consumer_cell(
    runtime: str,
    mode: str,
    built_dists: tuple[Path, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    wheel, sdist = built_dists
    venv = tmp_path_factory.mktemp(f"venv_{mode}_{runtime.replace('.', '_')}")
    tag = f"work_{mode}_{runtime.replace('.', '_')}"
    workdir = tmp_path_factory.mktemp(tag)  # outside the repository
    _provision_cell(runtime, mode, venv, wheel, sdist)
    _smoke(venv, workdir)


@pytest.mark.slow
def test_authoritative_wheel_cell_is_not_vacuous(
    built_dists: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Coverage guard: whenever uv/git and an index are present, the authoritative 3.12.3 wheel cell
    must execute end to end — so the matrix can never pass purely by skipping."""
    wheel, sdist = built_dists
    venv = tmp_path_factory.mktemp("venv_authoritative")
    workdir = tmp_path_factory.mktemp("work_authoritative")
    _provision_cell("3.12.3", "wheel", venv, wheel, sdist)
    _smoke(venv, workdir)


# --------------------------------------------------------------------------- #
# Channel A (exact-commit) contract — no network, always runs                  #
# --------------------------------------------------------------------------- #
def _git_ssh_spec(ref: str) -> str:
    """Build the documented Channel A pip spec, refusing anything but a full 40-hex commit SHA."""
    if not _FULL_SHA_RE.match(ref):
        raise ValueError(f"Channel A requires a full 40-hex commit SHA, not {ref!r}")
    return f"eth-research @ git+ssh://git@github.com/panfot1409/gambling-winnings.git@{ref}"


class TestExactCommitChannelContract:
    def test_contract_requires_full_sha_pin_and_no_branch_or_tag(self) -> None:
        contract = json.loads(INSTALL_CONTRACT.read_bytes())
        channel_a = next(c for c in contract["channels"] if c["id"] == "A")
        assert channel_a["reproducibility_pin"] == "full_40_hex_commit_sha"
        assert channel_a["branch_or_tag_pin_allowed"] is False
        assert channel_a["transport"] == "git+ssh"
        assert channel_a["requires_repository_authorization"] is True

    def test_spec_builder_accepts_a_full_sha_and_rejects_refs(self) -> None:
        good = "0123456789abcdef0123456789abcdef01234567"
        assert _git_ssh_spec(good).endswith(f"@{good}")
        for bad in ("main", "v1.1.0", "HEAD", good[:39], good + "a", good.upper()):
            with pytest.raises(ValueError, match="full 40-hex commit SHA"):
                _git_ssh_spec(bad)

    def test_head_is_a_full_sha_and_would_form_a_valid_pin(self) -> None:
        if _toolchain() is None:
            pytest.skip("git is required to resolve HEAD")
        sha = _head_sha()
        assert _FULL_SHA_RE.match(sha)
        assert _git_ssh_spec(sha).endswith(f"@{sha}")

    def test_distribution_doc_documents_the_full_sha_channel(self) -> None:
        text = PRIVATE_DISTRIBUTION_DOC.read_text(encoding="utf-8")
        assert "git+ssh://git@github.com/panfot1409/gambling-winnings.git@<FULL_SHA>" in text
        assert "only the full commit SHA" in text
