"""Tests for explainable KEMS advice."""

from kems_core import AdviceEngine, LearnedState, SimulationConfig, Snapshot


def test_day_rate_import_is_high_priority() -> None:
    """Grid import outside cheap periods should be surfaced immediately."""
    advice = AdviceEngine().evaluate(
        Snapshot(
            current_import_rate=28.3,
            off_peak=False,
            intelligent_slot=False,
            grid_import_kw=2.0,
        ),
        LearnedState(days_observed=10, confidence=70.0, ready=True),
        SimulationConfig(),
    )

    assert advice.primary.code == "day_rate_import"
    assert advice.primary.priority == 95
    assert advice.primary.estimated_saving_pence == 56.6


def test_learning_message_is_shown_early() -> None:
    """KEMS should clearly explain that it is still learning."""
    advice = AdviceEngine().evaluate(
        Snapshot(current_import_rate=3.49, off_peak=True),
        LearnedState(days_observed=2, confidence=8.0, ready=False),
        SimulationConfig(),
    )

    assert any(item.code == "learning" for item in advice.items)


def test_confirmed_happy_hour_import_is_not_warned_as_day_rate() -> None:
    """Verified joined reward hours suppress the ordinary tariff-only warning."""
    result = AdviceEngine().evaluate(
        Snapshot(
            current_import_rate=35.8828,
            off_peak=False,
            intelligent_slot=False,
            grid_import_kw=6.54,
        ),
        LearnedState(days_observed=20, confidence=90.0, ready=True),
        SimulationConfig(),
        happy_hour_reward_active=True,
    )

    assert result.primary.code == "happy_hour_reward_import"
    assert "credited separately" in result.primary.message
    assert result.primary.estimated_saving_pence is None
    assert "day_rate_import" not in [item.code for item in result.items]


def test_happy_hour_intent_requires_verified_runtime_authority() -> None:
    """Normal day-rate import must still alert without verified reward control."""
    result = AdviceEngine().evaluate(
        Snapshot(
            current_import_rate=35.8828,
            off_peak=False,
            intelligent_slot=False,
            grid_import_kw=6.54,
        ),
        LearnedState(days_observed=20, confidence=90.0, ready=True),
        SimulationConfig(),
        happy_hour_reward_active=False,
    )

    assert result.primary.code == "day_rate_import"
    assert "happy_hour_reward_import" not in [item.code for item in result.items]


def test_happy_hour_without_grid_import_does_not_claim_charge_savings() -> None:
    result = AdviceEngine().evaluate(
        Snapshot(current_import_rate=35.8828, grid_import_kw=0.0),
        LearnedState(days_observed=20, confidence=90.0, ready=True),
        SimulationConfig(),
        happy_hour_reward_active=True,
    )
    assert result.primary.code == "happy_hour_reward_import"
    assert result.primary.estimated_saving_pence is None
