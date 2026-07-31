"""``adaptive_expert_mixer_v1`` — causality, structure, anti-relabel, and non-evaluation.

Four things this suite exists to prove, in descending order of how badly a failure would matter:

1. **Causality.** The decision at bar ``t`` depends only on closes up to and including ``t``.
   Proved by the scalar oracle: extend the series with arbitrary future bars and the value at
   ``t`` must not move. A look-ahead bug is the failure that produces beautiful results and no
   real edge, and it is the one a reviewer cannot see by reading.
2. **Structure.** Long-only and unlevered are properties of the arithmetic here, not checks laid
   on top — a convex combination of ``{0, 1}`` exposures cannot leave ``[0, 1]``. The tests
   confirm the arithmetic actually has that property rather than trusting the docstring.
3. **Anti-relabel.** The candidate must be distinct from the permanently-rejected M3C candidate
   *and* from each of the three V2A families it uses as experts. Reusing a rejected family's
   parameters as an expert is legitimate; presenting the mixture as one of them is not.
4. **Non-evaluation.** No result, no metric, no ledger entry. The candidate is built and left
   unevaluated, and that state is asserted rather than assumed.

All series here are synthetic and seeded. No test reads a research partition.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.v2.candidates import MEANREV_SPEC, TREND_SPEC, VOL_SCALED_SPEC
from eth_research.v2f.mixer import (
    ADAPTIVE_EXPERT_MIXER_SPEC,
    EXPERT_NAMES,
    MEANREV_ENTRY_Z,
    MEANREV_LOOKBACK,
    REQUIRED_EXPERTS,
    TREND_HORIZON,
    WARMUP_BARS,
    AdaptiveExpertMixer,
    MixerError,
    _bar_losses,
    _eta,
    assert_mixer_specification_valid,
    build_adaptive_expert_mixer,
    mixer_signal_at,
    mixer_weight_at,
    run_mixer,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _series(seed: int, n: int = 500, drift: float = 0.0004, vol: float = 0.02) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


# --- 1. causality — the one that matters most -----------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3, 20260729])
def test_the_decision_at_t_is_unchanged_by_any_future_bar(seed: int) -> None:
    """Extend the series and the past must not move. This is the look-ahead test.

    Compares the whole prefix trajectory, not one point: a bug that leaked the future into a
    single early bar would survive a spot check at the end.
    """
    closes = _series(seed, n=400)
    prefix_len = 300
    base = run_mixer(closes[:prefix_len])

    for extra_seed in (99, 1234):
        extended = np.concatenate([closes[:prefix_len], _series(extra_seed, n=100)])
        extended_run = run_mixer(extended)
        for t in range(prefix_len):
            assert extended_run[t].decision == base[t].decision, f"decision moved at bar {t}"
            assert extended_run[t].mixture_weight == pytest.approx(
                base[t].mixture_weight, abs=0.0, rel=0.0
            ), f"mixture weight moved at bar {t}"
            assert extended_run[t].weights == base[t].weights, f"weights moved at bar {t}"


@pytest.mark.parametrize("t", [200, 250, 300, 399])
def test_the_scalar_oracle_agrees_with_the_vectorized_path(t: int) -> None:
    """The oracle is only evidence if the strategy actually agrees with it."""
    closes = _series(7, n=400)
    frame = pd.DataFrame({"close": closes})
    vectorized = AdaptiveExpertMixer().target_positions(frame).to_numpy()
    if t < WARMUP_BARS:
        pytest.skip("warm-up bars are forced to cash by design, not by the mixture")
    assert vectorized[t] == mixer_signal_at(closes[: t + 1])


def test_a_future_price_spike_cannot_reach_backwards() -> None:
    """A targeted probe: put an enormous bar at the end and check nothing before it moved."""
    closes = _series(11, n=300)
    spiked = closes.copy()
    spiked[-1] = closes[-1] * 50.0

    base = run_mixer(closes)
    probed = run_mixer(spiked)
    for t in range(len(closes) - 1):
        assert probed[t] == base[t], f"the spike at the end changed bar {t}"


def test_control_the_causality_probe_can_detect_a_leak() -> None:
    """A leak-detector that never fires is worthless. Prove it fires on a deliberate leak.

    The reference peeks at the series' FINAL close — a gross, unmistakable leak that shifts many
    bars when the series is extended. An earlier draft peeked one bar ahead instead, and that
    version passed against the leaky reference: for every ``t`` below the boundary both series
    share bar ``t+1``, so only the last bar could differ, and whether it did came down to the
    sign of one random draw. A control whose firing depends on a coin flip is not a control.
    """

    def leaky_at(closes: np.ndarray, t: int) -> float:
        return 1.0 if closes[-1] > closes[t] else 0.0

    closes = _series(13, n=120)
    extended = np.concatenate([closes, _series(14, n=40, drift=0.05)])
    moved = [t for t in range(len(closes)) if leaky_at(closes, t) != leaky_at(extended, t)]
    assert moved, "the probe failed to detect a deliberate look-ahead"

    # And the same comparison applied to the real mixer finds nothing, which is the point.
    base = run_mixer(closes)
    extended_run = run_mixer(extended)
    assert [t for t in range(len(closes)) if extended_run[t] != base[t]] == []


# --- 2. structure — long-only and unlevered by arithmetic -----------------------------------


@pytest.mark.parametrize("seed", [1, 5, 42, 7777])
def test_weights_stay_a_probability_vector(seed: int) -> None:
    for step in run_mixer(_series(seed, n=300)):
        assert all(w >= 0.0 for w in step.weights), "a Hedge weight went negative"
        assert sum(step.weights) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("seed", [1, 5, 42, 7777])
def test_the_mixture_weight_cannot_leave_the_unit_interval(seed: int) -> None:
    """Long-only and unlevered are unrepresentable here, not merely rejected."""
    for step in run_mixer(_series(seed, n=300)):
        assert 0.0 <= step.mixture_weight <= 1.0
        assert step.decision in (0.0, 1.0)


@pytest.mark.parametrize("seed", [3, 31])
def test_a_strongly_trending_series_concentrates_weight_on_the_winning_expert(seed: int) -> None:
    """A behavioural control: Hedge must actually learn, or every refusal above is trivial.

    This is not a performance claim and is not evidence about any market — it is a synthetic
    series constructed so one expert is obviously right, checking the mechanism responds.
    """
    closes = _series(seed, n=400, drift=0.004, vol=0.005)  # relentless up-drift
    final = run_mixer(closes)[-1]
    always_long_index = EXPERT_NAMES.index("always_long")
    cash_index = EXPERT_NAMES.index("cash")
    assert final.weights[always_long_index] > final.weights[cash_index], (
        "cash outweighed always-long on a monotone up-drift; the update has the wrong sign"
    )
    assert final.weights[always_long_index] > 0.25, "weight never moved off the uniform prior"


def test_a_flat_bar_charges_nobody() -> None:
    """Treating an unchanged close as "down" would hand cash a free win on every flat bar."""
    exposures = np.array([1.0, 1.0, 0.0, 0.0])
    assert np.all(_bar_losses(exposures, 0.0) == 0.0)
    assert np.array_equal(_bar_losses(exposures, 0.01), np.array([0.0, 0.0, 1.0, 1.0]))
    assert np.array_equal(_bar_losses(exposures, -0.01), np.array([1.0, 1.0, 0.0, 0.0]))


# --- 3. no fitted constants ------------------------------------------------------------------


def test_the_learning_rate_is_the_derived_anytime_rate() -> None:
    """§2.14 forbids hidden tuning. This rate comes from the regret bound; nothing is chosen."""
    n = len(EXPERT_NAMES)
    for step in (1, 2, 10, 365, 10_000):
        assert _eta(step) == pytest.approx(math.sqrt(8.0 * math.log(n) / step))
    assert _eta(1) > _eta(10) > _eta(10_000), "the anytime rate must decay in t"


def test_the_learning_rate_refuses_a_nonpositive_step() -> None:
    with pytest.raises(MixerError):
        _eta(0)


def test_the_inherited_experts_keep_their_v2a_parameters_exactly() -> None:
    """Re-tuning them here would be ``new_parameter_selection`` — a named prohibition.

    The mixer copies these values rather than importing the spec objects, so that editing a V2A
    spec cannot silently redefine this candidate's identity. This test is what turns that copy
    from a drift hazard into a reported disagreement.
    """
    assert MEANREV_SPEC.fixed_parameters["lookback"] == MEANREV_LOOKBACK
    assert MEANREV_SPEC.fixed_parameters["entry_z"] == MEANREV_ENTRY_Z
    assert TREND_SPEC.fixed_parameters["horizon"] == TREND_HORIZON


def test_the_warmup_is_the_max_expert_warmup_not_a_choice() -> None:
    assert max(TREND_HORIZON, MEANREV_LOOKBACK) == WARMUP_BARS


# --- 4. anti-relabel --------------------------------------------------------------------------


def test_the_specification_validates() -> None:
    assert_mixer_specification_valid()


def test_the_mixer_is_distinct_from_every_v2a_family_it_borrows_from() -> None:
    """Using rejected families as experts is legitimate; presenting the mixture as one is not."""
    mixer_fp = ADAPTIVE_EXPERT_MIXER_SPEC.fingerprint()
    for spec in (MEANREV_SPEC, VOL_SCALED_SPEC, TREND_SPEC):
        assert ADAPTIVE_EXPERT_MIXER_SPEC.candidate_id != spec.candidate_id
        assert ADAPTIVE_EXPERT_MIXER_SPEC.family != spec.family
        assert ADAPTIVE_EXPERT_MIXER_SPEC.signal_family != spec.signal_family
        assert mixer_fp != spec.fingerprint()


def test_the_specification_is_long_only_and_unlevered() -> None:
    assert ADAPTIVE_EXPERT_MIXER_SPEC.long_only is True
    assert ADAPTIVE_EXPERT_MIXER_SPEC.shorting is False
    assert ADAPTIVE_EXPERT_MIXER_SPEC.leverage is False
    assert ADAPTIVE_EXPERT_MIXER_SPEC.execution == "next_open_t_plus_1"


def test_the_expert_ordering_cannot_drift_from_the_required_set() -> None:
    """Same discipline as the paper-activation gates: name the requirement, not the ordering."""
    assert set(EXPERT_NAMES) == REQUIRED_EXPERTS
    assert len(EXPERT_NAMES) == len(REQUIRED_EXPERTS), "duplicate expert name"


def test_an_emptied_expert_ordering_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import eth_research.v2f.mixer as mixer_module

    monkeypatch.setattr(mixer_module, "EXPERT_NAMES", ())
    with pytest.raises(MixerError):
        mixer_module.assert_mixer_specification_valid()


# --- input validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        np.array([100.0, float("nan"), 101.0]),
        np.array([100.0, float("inf")]),
        np.array([100.0, 0.0, 101.0]),
        np.array([100.0, -5.0]),
    ],
    ids=["nan", "inf", "zero", "negative"],
)
def test_malformed_close_series_are_refused(bad: np.ndarray) -> None:
    with pytest.raises(MixerError):
        run_mixer(bad)


def test_a_two_dimensional_input_is_refused() -> None:
    with pytest.raises(MixerError):
        run_mixer(np.ones((3, 3)))


def test_an_empty_series_is_refused_by_the_oracles() -> None:
    with pytest.raises(MixerError):
        mixer_signal_at(np.array([]))
    with pytest.raises(MixerError):
        mixer_weight_at(np.array([]))


def test_a_frame_without_a_close_column_is_refused() -> None:
    with pytest.raises(MixerError):
        AdaptiveExpertMixer().target_positions(pd.DataFrame({"open": [1.0, 2.0]}))


def test_control_a_well_formed_frame_produces_aligned_binary_targets() -> None:
    index = pd.date_range("2020-01-01", periods=300, freq="D")
    frame = pd.DataFrame({"close": _series(21, n=300)}, index=index)
    targets = AdaptiveExpertMixer().target_positions(frame)
    assert list(targets.index) == list(index)
    assert set(targets.unique()) <= {0.0, 1.0}
    assert (targets.iloc[:WARMUP_BARS] == 0.0).all(), "warm-up bars must hold cash"


def test_the_engine_wiring_builds_with_a_neutral_overlay() -> None:
    strategy = build_adaptive_expert_mixer()
    assert strategy.name == "adaptive_expert_mixer_v1"
    assert strategy.warmup_bars == WARMUP_BARS
    assert strategy.risk.volatility_target is False
    assert strategy.risk.drawdown_breaker is False
    assert strategy.risk.max_exposure == 1.0


# --- 5. the candidate is built and NOT evaluated ---------------------------------------------


def test_no_evaluation_artifact_exists_for_this_candidate() -> None:
    """The whole point of the §12 determination: built, unevaluated, one-shot unspent.

    Searches the research tree for the candidate id. It may legitimately appear in documentation
    and in this repository's source, but a *result* or *decision* artifact naming it would mean
    the one-shot was spent, which nothing in this branch is authorized to do.
    """
    offenders: list[str] = []
    for path in (REPO_ROOT / "research").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in (".json", ".jsonl"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "adaptive_expert_mixer_v1" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"the candidate appears in research artifacts: {offenders}"


def test_the_sealed_ledgers_are_still_byte_empty_after_building_the_candidate() -> None:
    """Building a candidate must not touch a seal. Cheap, and it makes the claim executable."""
    for relpath in (
        "research/m3a/development_gate_access.jsonl",
        "research/m2b/test_evaluations.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        assert (REPO_ROOT / relpath).stat().st_size == 0, relpath


# --- 6. the preregistration exists, binds the source, and claims nothing ---------------------

#: The original record. Preserved byte-identical; superseded, never edited.
PREREG_V1_PATH = REPO_ROOT / "governance/v2f/adaptive_expert_mixer_v1_preregistration.json"
#: v2 superseded v1 after the pre-freeze semantic red team (V2F-MSF-1/2). Preserved, not edited.
PREREG_V2_PATH = REPO_ROOT / "governance/v2f/adaptive_expert_mixer_v1_preregistration_v2.json"
#: The ACTIVE record. v3 supersedes v2 with a proven documentation-only clarification (§4).
PREREG_PATH = REPO_ROOT / "governance/v2f/adaptive_expert_mixer_v1_preregistration_v3.json"


def _prereg() -> dict[str, object]:
    import json

    parsed: dict[str, object] = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    return parsed


def _prereg_v1() -> dict[str, object]:
    import json

    parsed: dict[str, object] = json.loads(PREREG_V1_PATH.read_text(encoding="utf-8"))
    return parsed


def _prereg_v2() -> dict[str, object]:
    import json

    parsed: dict[str, object] = json.loads(PREREG_V2_PATH.read_text(encoding="utf-8"))
    return parsed


def test_the_preregistration_exists_and_binds_this_specification() -> None:
    """Preregistration lives under governance/, not research/.

    That placement is what lets ``test_no_evaluation_artifact_exists_for_this_candidate`` stay a
    strong statement: a commitment made *before* evaluation is a governance act, while anything
    naming this candidate in ``research/`` would be evidence the one-shot was spent.
    """
    record = _prereg()
    assert record["kind"] == "v2f_candidate_preregistration"
    assert record["candidate_id"] == ADAPTIVE_EXPERT_MIXER_SPEC.candidate_id
    assert record["specification_fingerprint"] == ADAPTIVE_EXPERT_MIXER_SPEC.fingerprint()


def test_the_preregistration_pins_the_source_it_describes() -> None:
    """A preregistration that does not bind its own source describes nothing in particular."""
    import hashlib

    pinned = _prereg()["source_pin_sha256"]
    assert isinstance(pinned, dict)
    for relpath, digest in pinned.items():
        actual = hashlib.sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()
        assert actual == digest, f"{relpath} drifted from its pre-registered bytes"


def test_the_preregistration_records_the_candidate_as_unevaluated() -> None:
    record = _prereg()
    assert record["evaluation_status"] == "not_evaluated"
    assert record["one_shot_spent"] is False
    assert len(record["why_not_evaluated"]) >= 4  # type: ignore[arg-type]


def test_the_preregistration_states_the_weak_prior_before_any_result() -> None:
    """The point of preregistering a weak prior is that it cannot be revised afterwards."""
    prior = str(_prereg()["honest_prior_stated_before_any_result"])
    assert "WEAK" in prior
    assert "do not manufacture edge" in prior
    assert "research_stage_rejected" in prior


def test_the_preregistration_claims_no_performance() -> None:
    """A preregistration that leaks a result is not a preregistration."""
    disclaimers = _prereg()["explicitly_not_claimed"]
    assert isinstance(disclaimers, list)
    joined = " ".join(str(d) for d in disclaimers)
    assert "never been measured" in joined
    assert "unevaluated, which is a different state" in joined


# --- 7. V2F-MSF-1: the preregistered prior holds where it is claimed to hold ------------------
#
# Before the fix, run_mixer applied the full Hedge update across the warm-up. trend_signal_at
# returns 0.0 before its horizon, bitwise identical to cash's hard-coded 0.0, so the two weights
# moved in lockstep for all 200 bars and the trend expert inherited cash's record for an opinion
# it never expressed. The vector entering the first tradeable bar sat 0.4983 total-variation from
# uniform with always_long at exactly 0.000000. These tests fail against that code.


def _uniform() -> np.ndarray:
    return np.full(len(EXPERT_NAMES), 1.0 / len(EXPERT_NAMES))


@pytest.mark.parametrize("seed", [7, 19, 101, 2024])
def test_the_first_tradeable_bar_starts_from_the_preregistered_uniform_prior(seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, WARMUP_BARS + 300)))
    entering = np.array(run_mixer(closes)[WARMUP_BARS].weights)
    assert np.array_equal(entering, _uniform()), (
        f"weights entering the first tradeable bar are not uniform 1/N: {entering}"
    )


def test_no_expert_is_charged_for_a_bar_in_which_it_had_no_opinion() -> None:
    """Every warm-up weight vector must still be the prior — nothing is learned from sentinels."""
    rng = np.random.default_rng(7)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, WARMUP_BARS + 300)))
    for step in run_mixer(closes)[: WARMUP_BARS + 1]:
        assert np.array_equal(np.array(step.weights), _uniform())


def test_control_the_weights_do_move_once_trading_begins() -> None:
    """The control. Suppressing the update entirely would satisfy every assertion above."""
    rng = np.random.default_rng(7)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, WARMUP_BARS + 300)))
    final = np.array(run_mixer(closes)[-1].weights)
    assert not np.array_equal(final, _uniform()), "weights never moved; the mixture learns nothing"
    assert abs(float(final.sum()) - 1.0) < 1e-12


def test_learning_starts_at_the_full_anytime_rate_not_a_decayed_one() -> None:
    """``hedge_rounds`` counts rounds played, so the first real update uses eta(1), not eta(201).

    Indexing the rate by absolute bar would hand the first genuine round a rate an order of
    magnitude smaller than the bound prescribes, discarding the early adaptivity it exists for.
    """
    assert _eta(1) > 3.0
    assert _eta(WARMUP_BARS + 1) < 0.3

    rng = np.random.default_rng(7)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, WARMUP_BARS + 300)))
    steps = run_mixer(closes)
    # One round played between the first and second tradeable bars: the step must be eta(1)-sized,
    # which for a 0/1 loss means a charged expert loses a factor exp(-eta(1)) before renormalizing.
    before = np.array(steps[WARMUP_BARS].weights)
    after = np.array(steps[WARMUP_BARS + 1].weights)
    ratios = after / before
    spread = float(ratios.max() / ratios.min())
    assert spread == pytest.approx(math.exp(_eta(1)), rel=1e-9), (
        "the first Hedge round did not use the full anytime rate"
    )


# --- 8. the supersession is append-only ------------------------------------------------------


def test_the_superseded_record_is_preserved_byte_identical() -> None:
    """Append-only means the v1 record still exists and still hashes to what v2 says it does."""
    import hashlib

    supersedes = _prereg()["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["relpath"] == PREREG_V2_PATH.relative_to(REPO_ROOT).as_posix()
    actual = hashlib.sha256(PREREG_V2_PATH.read_bytes()).hexdigest()
    assert actual == supersedes["sha256"], "the superseded record was edited, not superseded"


def test_the_superseded_record_still_pins_the_source_it_described() -> None:
    """v1's pin must now be stale — that staleness is the evidence the code actually changed."""
    import hashlib

    v1_pin = _prereg_v1()["source_pin_sha256"]
    assert isinstance(v1_pin, dict)
    live = hashlib.sha256((REPO_ROOT / "src/eth_research/v2f/mixer.py").read_bytes()).hexdigest()
    assert v1_pin["src/eth_research/v2f/mixer.py"] != live
    v2_pin = _prereg_v2()["source_pin_sha256"]
    assert isinstance(v2_pin, dict)
    supersedes = _prereg()["supersedes"]
    assert isinstance(supersedes, dict)
    assert supersedes["superseded_source_pin"] == v2_pin["src/eth_research/v2f/mixer.py"]


def test_the_supersession_names_both_findings_and_stays_unevaluated() -> None:
    record = _prereg()
    corrections = record["corrections_from_v1"]
    assert isinstance(corrections, list)
    findings = {str(c["finding"]) for c in corrections}
    assert findings == {"V2F-MSF-1", "V2F-MSF-2"}
    assert record["evaluation_status"] == "not_evaluated"
    assert record["one_shot_spent"] is False
    # The active record's version advances as the append-only chain grows; what must not
    # change is that it still carries both findings and still reports the candidate unevaluated.
    assert isinstance(record["version"], int)
    assert record["version"] >= 2


def test_the_superseding_prior_is_weaker_not_stronger() -> None:
    """A supersession that improved the story would be exactly the abuse this guards against."""
    prior = str(_prereg()["honest_prior_stated_before_any_result"])
    assert "WEAKER than v1" in prior
    assert "No replacement mechanism is claimed" in prior
    not_claimed = _prereg()["explicitly_not_claimed"]
    assert isinstance(not_claimed, list)
    disclaimers = " ".join(str(d) for d in not_claimed)
    assert "Neither was chosen because it performed better" in disclaimers
    assert "adversarial-refutation stage has not run" in disclaimers


# --- 9. the v3 supersession is documentation-only, and says so provably ----------------------


def test_the_v3_supersession_did_not_change_the_specification_fingerprint() -> None:
    """A doc-only supersession that moved the fingerprint would be claiming a new algorithm.

    The contrast is the evidence: v2 DID move it (7608e9c9 -> f6bbcb8d) because MSF-1 changed
    the update rule. v3 must not, because it changed only prose.
    """
    assert _prereg()["specification_fingerprint"] == _prereg_v2()["specification_fingerprint"]
    assert _prereg()["specification_fingerprint"] == ADAPTIVE_EXPERT_MIXER_SPEC.fingerprint()
    assert _prereg_v2()["specification_fingerprint"] != _prereg_v1()["specification_fingerprint"]


def test_the_v3_behaviour_identity_proof_still_holds() -> None:
    """Re-derive the recorded trajectory hash rather than trusting the number in the file."""
    import hashlib

    proof = _prereg()["supersedes"]["behaviour_identity_proof"]  # type: ignore[index]
    digest = hashlib.sha256()
    for seed in range(25):
        rng = np.random.default_rng(seed)
        closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, 500)))
        for step in run_mixer(closes):
            digest.update(
                repr(
                    (step.weights, step.expert_exposures, step.mixture_weight, step.decision)
                ).encode()
            )
    assert digest.hexdigest() == proof["trajectory_sha256_after"]
    assert proof["trajectory_sha256_before"] == proof["trajectory_sha256_after"]


def test_the_whole_supersession_chain_is_preserved_byte_identical() -> None:
    """Append-only across all three records, each pinned by the next."""
    import hashlib

    chain = _prereg()["supersedes"]["chain"]  # type: ignore[index]
    assert [entry["version"] for entry in chain] == [1, 2]
    for entry in chain:
        actual = hashlib.sha256((REPO_ROOT / entry["relpath"]).read_bytes()).hexdigest()
        assert actual == entry["sha256"], f"{entry['relpath']} was edited, not superseded"
