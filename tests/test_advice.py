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
