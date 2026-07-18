"""Tests for the deterministic secret scanner (``tools/scan_secrets.py``).

Offline and fast by default: the planted-secret detection, redaction, whole-tree cleanliness,
self-scan, and RECORD/hex false-positive tests need neither ``uv`` nor ``git`` to *build*
anything (the tree scan uses ``git ls-files`` only to enumerate). The single build-dependent
test (a fresh wheel/sdist/payload scan) is marked ``slow`` and skips cleanly without ``uv``/``git``.

Every secret-shaped literal here is assembled from fragments via :func:`_a`, so this test file
contains no contiguous string any detector matches — the whole-tree scan (which includes this
file once committed) stays clean while still exercising real detections at runtime.

The tool is loaded via :func:`importlib.util.spec_from_file_location` (the pattern the existing
packaging/evidence tests use); the loaded module is registered in ``sys.modules`` so its
``@dataclass`` can resolve its own annotations under ``from __future__ import annotations``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCANNER_PATH = REPO / "tools" / "scan_secrets.py"
PRIVATE_RELEASE_PATH = REPO / "tools" / "private_release.py"

# The three sealed governance ledgers are byte-empty and must never be read; exclude them from the
# tree enumeration (they would contribute nothing but their content is out of bounds).
SEALED_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

# New deliverable files that may still be untracked in this session; union them into the tree scan
# so it covers them now and remains faithful after they are committed.
NEW_DELIVERABLES = (
    "tools/scan_secrets.py",
    "tests/test_secret_scanner.py",
    "tests/test_repo_privacy_contract.py",
    "tests/test_private_reproducibility_contract.py",
    "tests/test_private_release_failure_injection.py",
    "docs/V1_PRIVATE_REPRODUCIBILITY.md",
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # let the @dataclass resolve its stringized annotations
    spec.loader.exec_module(module)
    return module


SCAN = _load("scan_secrets", SCANNER_PATH)
PRIV = _load("private_release", PRIVATE_RELEASE_PATH)


def _a(*parts: str) -> str:
    """Assemble a secret at runtime from fragments (keeps this file self-clean)."""
    return "".join(parts)


# --------------------------------------------------------------------------- #
# (a) each secret class is detected                                            #
# --------------------------------------------------------------------------- #
# 40-char base64, mixes upper/lower/digit, not pure hex, high entropy.
_AWS_SECRET = _a("AbCd12efGh34", "IjKl56MnOp78", "QrSt90UvWx12", "YzAb")
_PLANTED: tuple[tuple[str, str, str], ...] = (
    (
        "pem_rsa",
        _a("-----", "BEGIN RSA ", "PRIVATE", " ", "KEY", "-----", "\nMIIBmawn==\n"),
        "pem_private_key",
    ),
    (
        "pem_openssh",
        _a("-----", "BEGIN OPENSSH ", "PRIVATE", " ", "KEY", "-----", "\nb3BlbnNz\n"),
        "pem_private_key",
    ),
    (
        "pem_plain",
        _a("-----", "BEGIN ", "PRIVATE", " ", "KEY", "-----", "\nMIIEvQ==\n"),
        "pem_private_key",
    ),
    (
        "pgp",
        _a("-----", "BEGIN PGP ", "PRIVATE", " ", "KEY", " BLOCK", "-----", "\nlQ==\n"),
        "pgp_private_key",
    ),
    ("aws_key_id", _a("A", "KIA") + "1234ABCD5678EFGH", "aws_access_key_id"),
    ("aws_secret", _AWS_SECRET, "aws_secret_access_key"),
    (
        "github",
        _a("gh", "p", "_") + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "github_token",
    ),
    ("slack", _a("xo", "xb", "-") + "2f3a4b5c6d7e8f9a0b1c2d3e", "slack_token"),
    (
        "assign_api_key",
        _a("api", '_key = "', "Zx9Qw8Er7Ty6Ui5Op3", '"'),
        "secret_assignment",
    ),
    (
        "assign_password",
        _a("pass", 'word: "', "H0rse-Battery-Staple-9", '"'),
        "secret_assignment",
    ),
    (
        "assign_client_secret",
        _a("client", '_secret="', "Q1w2E3r4T5y6U7i8O9p0", '"'),
        "secret_assignment",
    ),
)


@pytest.mark.parametrize(("label", "blob", "detector"), _PLANTED, ids=[p[0] for p in _PLANTED])
def test_planted_secret_of_each_class_is_detected(label: str, blob: str, detector: str) -> None:
    findings = SCAN.scan_bytes(f"planted_{label}.txt", blob.encode("utf-8"))
    detectors = {f.detector for f in findings}
    assert detector in detectors, f"{label}: expected {detector}, got {sorted(detectors)}"


# --------------------------------------------------------------------------- #
# (b) a redacted fingerprint — never the raw secret — is what is reported      #
# --------------------------------------------------------------------------- #
def test_finding_reports_redacted_fingerprint_not_the_raw_secret() -> None:
    findings = SCAN.scan_bytes("cred.txt", _AWS_SECRET.encode("utf-8"))
    assert findings
    finding = next(f for f in findings if f.detector == "aws_secret_access_key")
    # The raw secret must appear in NONE of the finding's stringifiable surfaces.
    assert _AWS_SECRET not in str(finding)
    assert _AWS_SECRET not in repr(finding)
    assert _AWS_SECRET not in finding.fingerprint
    assert finding.fingerprint == f"aws_secret_access_key:sha256:{_digest12(_AWS_SECRET)}"
    # The fingerprint is a deterministic function of the raw match.
    again = SCAN.scan_bytes("other.txt", _AWS_SECRET.encode("utf-8"))
    assert finding.fingerprint == again[0].fingerprint


def _digest12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def test_secret_assignment_placeholder_values_are_not_reported() -> None:
    # Obvious placeholders and whitespace-bearing values are not live secrets.
    for value in ("changeme", "your-token-here", "example-secret-000", "<REDACTED-VALUE>"):
        blob = _a("api", '_key = "', value, '"')
        assert SCAN.scan_bytes("cfg.py", blob.encode("utf-8")) == []
    spaced = _a("token", ' = "', "yes please sir", '"')
    assert SCAN.scan_bytes("cfg.py", spaced.encode("utf-8")) == []


# --------------------------------------------------------------------------- #
# (c) the whole committed repo tree is clean                                   #
# --------------------------------------------------------------------------- #
def _repo_tree_files() -> list[Path]:
    proc = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    tracked = {(REPO / line).resolve() for line in proc.stdout.splitlines() if line}
    extra = {(REPO / rel).resolve() for rel in NEW_DELIVERABLES if (REPO / rel).is_file()}
    sealed = {(REPO / rel).resolve() for rel in SEALED_LEDGERS}
    return sorted((tracked | extra) - sealed)


def test_whole_repo_tree_has_no_secret() -> None:
    files = _repo_tree_files()
    # Guard against a vacuous scan and prove reach into each executable/evidence surface.
    names = {p.relative_to(REPO).as_posix() for p in files}
    assert len(files) > 100
    assert "tools/scan_secrets.py" in names
    assert "tools/private_release.py" in names
    assert "pyproject.toml" in names
    findings = []
    for path in files:
        findings.extend(SCAN.scan_bytes(path.relative_to(REPO).as_posix(), path.read_bytes()))
    assert findings == [], "\n".join(str(f) for f in findings)


# --------------------------------------------------------------------------- #
# (e) scanning the scanner file itself finds nothing                           #
# --------------------------------------------------------------------------- #
def test_scanner_file_does_not_self_match() -> None:
    assert SCAN.scan_bytes("tools/scan_secrets.py", SCANNER_PATH.read_bytes()) == []
    assert SCAN.scan_paths([SCANNER_PATH]) == []


# --------------------------------------------------------------------------- #
# (f) sha256 digests and wheel RECORD base64 are not false-positived           #
# --------------------------------------------------------------------------- #
def test_sha256_digests_and_git_shas_are_not_secrets() -> None:
    # 64-hex SHA-256 digests are all over the repo (manifests, ledgers, SBOM) — never secrets.
    digests = "\n".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(300))
    assert SCAN.scan_bytes("digests.txt", digests.encode("utf-8")) == []
    # 40-hex git SHAs (workflow action pins, commit fields) are not AWS secret keys.
    shas = "\n".join(hashlib.sha1(str(i).encode()).hexdigest() for i in range(300))
    assert SCAN.scan_bytes("shas.txt", shas.encode("utf-8")) == []


def test_wheel_record_base64_is_not_a_secret() -> None:
    # A wheel RECORD line is ``<path>,sha256=<urlsafe-b64 digest>,<size>``; the digest is 43 chars
    # over the url-safe alphabet (``-``/``_``) — longer than 40 and outside ``[A-Za-z0-9/+]`` runs.
    lines = []
    for i in range(50):
        digest = urlsafe_b64encode(hashlib.sha256(str(i).encode()).digest()).rstrip(b"=").decode()
        assert len(digest) == 43
        lines.append(f"eth_research/mod_{i}.py,sha256={digest},{i * 7}")
    record = "\n".join(lines) + "\n"
    assert SCAN.scan_bytes("eth_research-1.1.0.dist-info/RECORD", record.encode("utf-8")) == []


# --------------------------------------------------------------------------- #
# scan_paths + main() behaviour (API + CLI, offline)                           #
# --------------------------------------------------------------------------- #
def test_scan_paths_and_main_flag_a_planted_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "leak.py").write_bytes(
        (_a("api", '_key = "', "Zx9Qw8Er7Ty6Ui5Op3", '"') + "\n").encode()
    )
    findings = SCAN.scan_paths([tmp_path])
    assert [f.detector for f in findings] == ["secret_assignment"]
    assert _AWS_SECRET not in capsys.readouterr().err  # nothing raw leaked by scanning

    assert SCAN.main(["--repo-root", str(tmp_path)]) == 1  # non-zero exit on any finding
    err = capsys.readouterr().err
    assert "secret scan FAILED" in err
    assert "Zx9Qw8Er7Ty6Ui5Op3" not in err  # the raw value is never printed


def test_main_is_clean_on_a_secret_free_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "ok.py").write_text("value = 42\n", encoding="utf-8")
    assert SCAN.main(["--repo-root", str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# (d) slow: a freshly built wheel + sdist + assembled payload are clean        #
# --------------------------------------------------------------------------- #
def _uv_available() -> bool:
    import shutil

    return shutil.which("uv") is not None and shutil.which("git") is not None


def _wheel_members(data: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if not name.endswith("/"):
                members[name] = zf.read(name)
    return members


def _sdist_members(data: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            if member.isfile():
                extracted = tf.extractfile(member)
                members[member.name] = b"" if extracted is None else extracted.read()
    return members


@pytest.mark.slow
def test_built_wheel_sdist_and_payload_have_no_secret() -> None:
    if not _uv_available():
        pytest.skip("uv/git required to build the distribution")
    try:
        wheel_bytes, sdist_bytes = PRIV._build_wheel_and_sdist(REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    payload_bytes = PRIV.assemble_payload_bytes(REPO, wheel_bytes, sdist_bytes)

    blobs: dict[str, bytes] = {
        "eth_research-1.1.0-py3-none-any.whl": wheel_bytes,
        "eth_research-1.1.0.tar.gz": sdist_bytes,
        "eth-research-1.1.0-private-payload.tar": payload_bytes,
    }
    # Also scan the DECOMPRESSED members, so the wheel RECORD (url-safe base64) and every source
    # file are checked in cleartext, not only the opaque zip/gzip container bytes.
    for name, data in _wheel_members(wheel_bytes).items():
        blobs[f"wheel::{name}"] = data
    for name, data in _sdist_members(sdist_bytes).items():
        blobs[f"sdist::{name}"] = data

    findings = []
    for name, data in blobs.items():
        findings.extend(SCAN.scan_bytes(name, data))
    assert findings == [], "\n".join(str(f) for f in findings)
    # The RECORD must actually have been present and scanned (guard against a vacuous pass).
    assert any(name.endswith(".dist-info/RECORD") for name in _wheel_members(wheel_bytes))
