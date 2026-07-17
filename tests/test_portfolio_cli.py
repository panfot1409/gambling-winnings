"""The offline portfolio/universe CLI: commands, determinism, exit codes, and offline posture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.api.serialization import canonical_json_bytes
from eth_research.portfolio import cli
from eth_research.portfolio.cli import main

# The stable exit-code scheme this CLI documents (mirrors eth_research.cli.app's grouping).
_USAGE_EXIT = 2
_VALIDATION_EXIT = 4


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _demo_result_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Write a real, canonical PortfolioResult produced by ``portfolio demo --full`` to a file."""
    code, out, _ = _run(["portfolio", "demo", "--full", "--json"], capsys)
    assert code == 0
    path = tmp_path / "result.json"
    path.write_bytes(out.encode("utf-8"))
    return path


# --------------------------------------------------------------------------- #
# universe inspect / validate
# --------------------------------------------------------------------------- #
def test_universe_inspect_json_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    code, out_a, _ = _run(["universe", "inspect", "--json"], capsys)
    assert code == 0
    payload = json.loads(out_a)
    assert len(payload["fingerprint"]) == 64
    assert payload["base_currency"] == "USD"
    assert payload["required_fx_pairs"] == [["EUR", "USD"]]

    # running it again yields byte-identical stdout (no wall clock, no randomness)
    _, out_b, _ = _run(["universe", "inspect", "--json"], capsys)
    assert out_a == out_b


def test_universe_inspect_full_emits_canonical_spec(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["universe", "inspect", "--full", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["schema_version"] == 1
    assert len(payload["instruments"]) == 3


def test_universe_validate_demo_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --demo round-trips the built-in reference universe through UniverseSpec.from_mapping
    code, demo_out, _ = _run(["universe", "validate", "--demo", "--json"], capsys)
    assert code == 0
    demo_payload = json.loads(demo_out)
    assert demo_payload["valid"] is True
    assert len(demo_payload["fingerprint"]) == 64

    # --in fully binds a file that describes the reference universe (matching calendar fingerprints)
    _, spec_json, _ = _run(["universe", "inspect", "--full", "--json"], capsys)
    universe_file = tmp_path / "universe.json"
    universe_file.write_bytes(spec_json.encode("utf-8"))
    code, file_out, _ = _run(["universe", "validate", "--in", str(universe_file), "--json"], capsys)
    assert code == 0
    file_payload = json.loads(file_out)
    assert file_payload["valid"] is True
    # the file describes exactly the reference universe, so validation reports the same identity
    assert file_payload["fingerprint"] == demo_payload["fingerprint"]


def test_universe_validate_requires_a_source(capsys: pytest.CaptureFixture[str]) -> None:
    # neither --in nor --demo is a usage error (argparse exits 2 without a traceback)
    with pytest.raises(SystemExit) as excinfo:
        main(["universe", "validate"])
    assert excinfo.value.code == _USAGE_EXIT
    assert "Traceback" not in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# portfolio demo / run
# --------------------------------------------------------------------------- #
def test_portfolio_demo_json_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    code, out_a, _ = _run(["portfolio", "demo", "--json"], capsys)
    assert code == 0
    payload = json.loads(out_a)
    assert len(payload["result_id"]) == 64
    assert payload["terminal_equity"] > 0.0
    assert payload["initial_equity"] == 120000.0

    # a second run over identical inputs prints byte-identical stdout
    _, out_b, _ = _run(["portfolio", "demo", "--json"], capsys)
    assert out_a == out_b


def test_portfolio_run_is_an_alias_of_demo(capsys: pytest.CaptureFixture[str]) -> None:
    _, demo_out, _ = _run(["portfolio", "demo", "--full", "--json"], capsys)
    _, run_out, _ = _run(["portfolio", "run", "--full", "--json"], capsys)
    assert demo_out == run_out


# --------------------------------------------------------------------------- #
# portfolio verify
# --------------------------------------------------------------------------- #
def test_portfolio_verify_accepts_a_real_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result_file = _demo_result_file(tmp_path, capsys)
    code, out, _ = _run(["portfolio", "verify", "--result", str(result_file), "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["valid"] is True
    assert len(payload["result_id"]) == 64


def test_portfolio_verify_rejects_a_tampered_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result_file = _demo_result_file(tmp_path, capsys)
    # a well-formed canonical file whose terminal equity no longer reconciles with its attribution
    data = json.loads(result_file.read_bytes())
    data["terminal_equity"] = data["terminal_equity"] + 1000.0
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(canonical_json_bytes(data))

    code, out, err = _run(["portfolio", "verify", "--result", str(tampered)], capsys)
    assert code == _VALIDATION_EXIT
    assert out == ""  # nothing printed to stdout on failure
    assert "Traceback" not in err  # a clean single-line error, never a traceback
    assert err.startswith("error: ")


def test_portfolio_verify_rejects_non_canonical_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    garbage = tmp_path / "garbage.json"
    garbage.write_bytes(b"{ this is not json\n")
    code, _, err = _run(["portfolio", "verify", "--result", str(garbage)], capsys)
    assert code == _VALIDATION_EXIT
    assert "Traceback" not in err


def test_portfolio_verify_missing_file_is_a_clean_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does_not_exist.json"
    code, _, err = _run(["portfolio", "verify", "--result", str(missing)], capsys)
    assert code == _VALIDATION_EXIT  # a missing input is caller error, not an internal (70) bug
    assert "Traceback" not in err


# --------------------------------------------------------------------------- #
# usage errors
# --------------------------------------------------------------------------- #
def test_no_subcommand_is_a_clean_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in ([], ["universe"], ["portfolio"]):
        assert main(argv) == _USAGE_EXIT
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["portfolio", "verify"],  # missing the required --result
        ["portfolio", "bogus"],  # unknown subcommand
        ["nonsense"],  # unknown group
    ],
)
def test_bad_arguments_exit_two_without_traceback(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == _USAGE_EXIT
    assert "Traceback" not in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# offline / no-dynamic-code posture
# --------------------------------------------------------------------------- #
def test_cli_module_is_offline_and_free_of_dynamic_code() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for banned in ("eval(", "exec(", "import socket", "requests", "urllib.request"):
        assert banned not in source
