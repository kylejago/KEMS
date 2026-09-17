"""Regression coverage for Alpha9.51 Power Down post-event reporting."""

from datetime import UTC, datetime
from pathlib import Path

from custom_components.kems import alpha951_power_down_post_event as alpha951
from custom_components.kems.kems_core import PowerDownResult, SimulationState


def _completed(session_id: str, bonus: float) -> PowerDownResult:
    return PowerDownResult(
        available=True,
        session_id=session_id,
        session_start=datetime(2026, 9, 17, 17, 0, tzinfo=UTC),
        session_end=datetime(2026, 9, 17, 18, 0, tzinfo=UTC),
        starting_simulated_soc_percent=60.4,
        finishing_simulated_soc_percent=49.4,
        rewardable_reduction_kwh=1.502,
        bonus_pence=bonus,
        fixed_export_income_pence=0.0,
        combined_income_pence=bonus,
        maximum_inverter_output_kw=2.669,
        ev_successfully_blocked=True,
        plan_safe_throughout=True,
        completed_successfully=True,
        completion_reason="completed",
    )


def test_completed_event_credit_replaces_stale_estimate(monkeypatch) -> None:
    """Recorded completion evidence is authoritative once the event is over."""
    monkeypatch.setattr(alpha951, "_today_completed_results", lambda: [_completed("6302", 12.76)])
    simulation = SimulationState(
        simulated_cost_pence=-500.24,
        saving_pence=100.0,
        simulated_system_value_pence=834.36,
        simulated_saving_session_bonus_pence=12.65,
    )

    result = alpha951._reconcile_completed_credit(simulation)

    assert result.simulated_saving_session_bonus_pence == 12.76
    assert result.simulated_cost_pence == -500.35
    assert result.saving_pence == 100.11
    assert result.simulated_system_value_pence == 834.47


def test_completed_history_deduplicates_by_session_id() -> None:
    """Repeated persistence of one event must not duplicate dashboard history."""
    first = _completed("6302", 12.65).to_dict()
    corrected = _completed("6302", 12.76).to_dict()
    second = _completed("6303", 8.5).to_dict()

    history = alpha951._normalise_history([first, corrected, second])

    assert [item.session_id for item in history] == ["6302", "6303"]
    assert history[0].bonus_pence == 12.76


def test_dashboard_surfaces_completed_sessions_and_event_credit() -> None:
    """Both the event card and daily cost ledger expose post-event evidence."""
    root = Path(__file__).resolve().parents[1]
    card = (root / "custom_components/kems/power_down_dashboard_card.yaml").read_text()
    patch = (root / "custom_components/kems/alpha951_power_down_post_event.py").read_text()

    assert "Completed sessions today" in card
    assert "completed_sessions_today" in card
    assert "supplier-settled" in card
    assert "Power Down event credit" in patch
    assert "power_down_credit_today_pence" in patch


def test_alpha951_keeps_control_authority_out_of_scope() -> None:
    """Reporting patch must not add control/write service calls."""
    source = Path(alpha951.__file__).read_text()

    assert "async_call(" not in source
    assert "foxess_modbus" not in source
    assert "commands_permitted = True" not in source
