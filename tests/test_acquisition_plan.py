"""Acquisition request-plan and receipt schema: tiling + adversarial parsing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eth_research.data.acquisition_plan import (
    ACQUISITION_USER_AGENT,
    AcquisitionAttemptReceipt,
    AcquisitionPlanError,
    AcquisitionRequestPlan,
    AcquisitionResponseReceipt,
    AcquisitionWindow,
    build_acquisition_plan,
    load_acquisition_plan,
    main,
)
from eth_research.data.coinbase import canonical_utc_request

DAY = pd.Timedelta(days=1)
START = pd.Timestamp("2016-05-18", tz="UTC")
END = pd.Timestamp("2017-06-18", tz="UTC")


def valid_plan() -> AcquisitionRequestPlan:
    return build_acquisition_plan(overall_start=START, overall_end=END)


def valid_window(**overrides: Any) -> AcquisitionWindow:
    start = overrides.pop("window_start", START)
    end = overrides.pop("window_end", START + 100 * DAY)
    fields: dict[str, Any] = {
        "ordinal": 0,
        "window_start": start,
        "window_end": end,
        "requested_start": canonical_utc_request(start),
        "requested_end": canonical_utc_request(end - DAY),
        "filename": "coinbase-eth-usd-1d_0000.json",
    }
    fields.update(overrides)
    return AcquisitionWindow(**fields)


class TestBuildAndRoundTrip:
    def test_build_tiles_and_round_trips(self) -> None:
        plan = valid_plan()
        raw = plan.to_json_bytes()
        assert AcquisitionRequestPlan.from_json_bytes(raw).to_json_bytes() == raw
        assert plan.expected_request_count == len(plan.windows)
        # windows tile [start, end) contiguously
        assert plan.windows[0].window_start == START
        assert plan.windows[-1].window_end == END

    def test_plan_sha_is_stable(self) -> None:
        assert valid_plan().plan_sha256() == valid_plan().plan_sha256()

    def test_single_window_when_range_fits(self) -> None:
        plan = build_acquisition_plan(overall_start=START, overall_end=START + 50 * DAY)
        assert plan.expected_request_count == 1

    def test_window_never_exceeds_the_cap(self) -> None:
        plan = build_acquisition_plan(overall_start=START, overall_end=START + 900 * DAY)
        assert all((w.window_end - w.window_start) <= 299 * DAY for w in plan.windows)


class TestWindowValidation:
    @pytest.mark.parametrize(
        "filename",
        [
            "../escape.json",
            "sub/dir.json",
            "/abs/path.json",
            "a;rm -rf.json",
            "a b.json",
            "a$(whoami).json",
            "a|b.json",
            "..json",
        ],
    )
    def test_unsafe_filename_is_rejected(self, filename: str) -> None:
        with pytest.raises(ValueError, match="filename"):
            valid_window(filename=filename)

    def test_non_json_filename_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"\.json"):
            valid_window(filename="chunk_0000.txt")

    def test_non_utc_window_is_rejected(self) -> None:
        # Construct directly: a naive window_start must be refused by the
        # window itself (the requested params are never reached).
        with pytest.raises(ValueError, match="window_start"):
            AcquisitionWindow(
                ordinal=0,
                window_start=pd.Timestamp("2016-05-18"),  # naive
                window_end=START + 100 * DAY,
                requested_start="2016-05-18T00:00:00Z",
                requested_end="2016-08-25T00:00:00Z",
                filename="chunk_0000.json",
            )

    def test_unaligned_window_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_start"):
            AcquisitionWindow(
                ordinal=0,
                window_start=pd.Timestamp("2016-05-18T06:00:00Z"),  # not day-aligned
                window_end=START + 100 * DAY,
                requested_start="2016-05-18T06:00:00Z",
                requested_end="2016-08-25T00:00:00Z",
                filename="chunk_0000.json",
            )

    def test_swapped_window_bounds_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must precede"):
            valid_window(window_start=START + 10 * DAY, window_end=START)

    def test_window_spanning_300_days_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="more than 299"):
            valid_window(window_start=START, window_end=START + 300 * DAY)

    def test_window_spanning_exactly_299_days_is_accepted(self) -> None:
        valid_window(window_start=START, window_end=START + 299 * DAY)

    def test_non_canonical_requested_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="requested_start"):
            valid_window(requested_start="2016-05-18T00:00:00Z&granularity=60")

    def test_bool_ordinal_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ordinal"):
            valid_window(ordinal=True)


class TestPlanValidation:
    def _payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(valid_plan().to_json_bytes())
        return payload

    def _reparse(self, payload: dict[str, Any]) -> AcquisitionRequestPlan:
        return AcquisitionRequestPlan.from_json_bytes(json.dumps(payload).encode("utf-8"))

    @pytest.mark.parametrize(
        ("field", "value", "match"),
        [
            ("endpoint", "https://evil.example.com/candles", "endpoint must be"),
            ("endpoint", "http://api.exchange.coinbase.com/products/ETH-USD/candles", "endpoint"),
            ("product", "BTC-USD", "product must be"),
            ("venue", "binance", "venue must be"),
            ("granularity_seconds", 3600, "granularity_seconds must be"),
            ("max_candles_per_request", 1000, "max_candles_per_request must be"),
            ("max_window_days", 300, "exceeds the cautious cap"),
            ("no_repair", False, "no_repair must be true"),
            ("documentation_url", "https://evil.example.com", "documentation_url must be"),
        ],
    )
    def test_rejected_field(self, field: str, value: Any, match: str) -> None:
        payload = self._payload()
        payload[field] = value
        with pytest.raises(ValueError, match=match):
            self._reparse(payload)

    def test_swapped_overall_bounds_rejected(self) -> None:
        with pytest.raises(AcquisitionPlanError, match="must precede"):
            build_acquisition_plan(overall_start=END, overall_end=START)

    def test_reordered_windows_break_tiling(self) -> None:
        payload = self._payload()
        payload["windows"] = list(reversed(payload["windows"]))
        with pytest.raises(ValueError, match=r"ordinals must be contiguous|tile"):
            self._reparse(payload)

    def test_gap_between_windows_is_rejected(self) -> None:
        payload = self._payload()
        # shrink the first window so a one-day gap opens before the second
        first = payload["windows"][0]
        new_end = pd.Timestamp(first["window_end"]) - DAY
        first["window_end"] = new_end.isoformat()
        first["requested_end"] = canonical_utc_request(new_end - DAY)
        with pytest.raises(ValueError, match=r"tile|without gaps"):
            self._reparse(payload)

    def test_duplicate_filenames_rejected(self) -> None:
        payload = self._payload()
        payload["windows"][1]["filename"] = payload["windows"][0]["filename"]
        with pytest.raises(ValueError, match="unique"):
            self._reparse(payload)

    def test_non_contiguous_ordinals_rejected(self) -> None:
        payload = self._payload()
        payload["windows"][1]["ordinal"] = 5
        with pytest.raises(ValueError, match="ordinals must be contiguous"):
            self._reparse(payload)

    def test_empty_windows_rejected(self) -> None:
        payload = self._payload()
        payload["windows"] = []
        with pytest.raises(ValueError, match="non-empty"):
            self._reparse(payload)


class TestStrictParsing:
    def test_unknown_key_rejected(self) -> None:
        payload = json.loads(valid_plan().to_json_bytes())
        payload["evil"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['evil'\]"):
            AcquisitionRequestPlan.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_missing_key_rejected(self) -> None:
        payload = json.loads(valid_plan().to_json_bytes())
        del payload["venue"]
        with pytest.raises(ValueError, match=r"missing=\['venue'\]"):
            AcquisitionRequestPlan.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_duplicate_key_rejected(self) -> None:
        raw = valid_plan().to_json_bytes().decode("utf-8")
        dup = raw.replace(
            '  "venue": "coinbase-exchange",',
            '  "venue": "coinbase-exchange",\n  "venue": "binance",',
            1,
        )
        assert dup != raw
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            AcquisitionRequestPlan.from_json_bytes(dup.encode("utf-8"))

    def test_non_finite_number_rejected(self) -> None:
        raw = valid_plan().to_json_bytes().decode("utf-8")
        bad = raw.replace('"granularity_seconds": 86400', '"granularity_seconds": Infinity', 1)
        with pytest.raises(ValueError, match="non-finite"):
            AcquisitionRequestPlan.from_json_bytes(bad.encode("utf-8"))

    def test_extra_field_in_window_rejected(self) -> None:
        payload = json.loads(valid_plan().to_json_bytes())
        payload["windows"][0]["evil"] = "x"
        with pytest.raises(ValueError, match="window keys do not match"):
            AcquisitionRequestPlan.from_json_bytes(json.dumps(payload).encode("utf-8"))


def valid_response(
    ordinal: int = 0, filename: str = "chunk_0000.json"
) -> AcquisitionResponseReceipt:
    return AcquisitionResponseReceipt(
        ordinal=ordinal,
        filename=filename,
        http_status=200,
        byte_length=100,
        sha256="a" * 64,
        retrieved_at=pd.Timestamp("2026-07-12T00:00:00Z"),
        content_type="application/json",
    )


def valid_receipt(**overrides: Any) -> AcquisitionAttemptReceipt:
    fields: dict[str, Any] = {
        "receipt_schema_version": 1,
        "package_version": "0.3.0",
        "plan_sha256": "b" * 64,
        "attempt_id": "attempt-001",
        "workflow_run_id": "12345",
        "source_commit": "c" * 40,
        "curl_version": "curl 8.5.0",
        "runner": "github-actions ubuntu-24.04",
        "user_agent": ACQUISITION_USER_AGENT,
        "responses": (valid_response(),),
    }
    fields.update(overrides)
    return AcquisitionAttemptReceipt(**fields)


class TestReceipt:
    def test_round_trip(self) -> None:
        receipt = valid_receipt(
            responses=(valid_response(0, "a.json"), valid_response(1, "b.json"))
        )
        raw = receipt.to_json_bytes()
        assert AcquisitionAttemptReceipt.from_json_bytes(raw).to_json_bytes() == raw

    def test_non_200_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="http_status must be 200"):
            valid_response().__class__(
                ordinal=0,
                filename="a.json",
                http_status=429,
                byte_length=100,
                sha256="a" * 64,
                retrieved_at=pd.Timestamp("2026-07-12T00:00:00Z"),
                content_type="application/json",
            )

    def test_naive_retrieved_at_rejected(self) -> None:
        with pytest.raises(ValueError, match="retrieved_at"):
            AcquisitionResponseReceipt(
                ordinal=0,
                filename="a.json",
                http_status=200,
                byte_length=100,
                sha256="a" * 64,
                retrieved_at=pd.Timestamp("2026-07-12T00:00:00"),  # naive
                content_type="application/json",
            )

    def test_bad_source_commit_rejected(self) -> None:
        with pytest.raises(ValueError, match="source_commit"):
            valid_receipt(source_commit="not-a-sha")

    def test_non_contiguous_response_ordinals_rejected(self) -> None:
        with pytest.raises(ValueError, match="ordinals must be contiguous"):
            valid_receipt(responses=(valid_response(0, "a.json"), valid_response(3, "b.json")))

    def test_duplicate_response_filenames_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            valid_receipt(responses=(valid_response(0, "a.json"), valid_response(1, "a.json")))

    def test_empty_responses_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            valid_receipt(responses=())

    def test_unknown_key_rejected(self) -> None:
        payload = json.loads(valid_receipt().to_json_bytes())
        payload["evil"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['evil'\]"):
            AcquisitionAttemptReceipt.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestPlanGeneratorCLI:
    def test_generates_valid_plan(self, tmp_path: Path) -> None:
        out = tmp_path / "acquisition_request_plan.json"
        rc = main(["--start", "2016-05-18", "--end", "2017-06-18", "--out", str(out)])
        assert rc == 0
        plan = load_acquisition_plan(out)
        assert plan.overall_start == START
        assert plan.overall_end == END
        assert (
            plan.plan_sha256()
            == build_acquisition_plan(overall_start=START, overall_end=END).plan_sha256()
        )

    def test_rejects_unaligned_start(self, tmp_path: Path) -> None:
        rc = main(
            [
                "--start",
                "2016-05-18T06:00",
                "--end",
                "2017-06-18",
                "--out",
                str(tmp_path / "p.json"),
            ]
        )
        assert rc == 1
        assert not (tmp_path / "p.json").exists()

    def test_rejects_swapped_bounds(self, tmp_path: Path) -> None:
        rc = main(
            ["--start", "2017-06-18", "--end", "2016-05-18", "--out", str(tmp_path / "p.json")]
        )
        assert rc == 1

    def test_refuses_overwrite(self, tmp_path: Path) -> None:
        out = tmp_path / "p.json"
        assert main(["--start", "2016-05-18", "--end", "2017-06-18", "--out", str(out)]) == 0
        assert main(["--start", "2016-05-18", "--end", "2017-06-18", "--out", str(out)]) == 1

    def test_overwrite_flag_allows_replacement(self, tmp_path: Path) -> None:
        out = tmp_path / "p.json"
        assert main(["--start", "2016-05-18", "--end", "2017-06-18", "--out", str(out)]) == 0
        assert (
            main(["--start", "2016-05-18", "--end", "2017-06-18", "--out", str(out), "--overwrite"])
            == 0
        )
