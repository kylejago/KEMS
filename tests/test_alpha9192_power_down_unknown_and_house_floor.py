"""Alpha9.192: absent Power Down credit and physical 10% reserve guards."""

from datetime import UTC, datetime
from pathlib import Path

from custom_components.kems import alpha951_power_down_post_event as reporting
from custom_components.kems.kems_core import PowerDownResult, SimulationState


def _event(bonus: float | None) -> PowerDownResult:
    return PowerDownResult(
        available=True,
        session_id="8342",
        session_start=datetime(2026, 11, 9, 17, tzinfo=UTC),
        session_end=datetime(2026, 11, 9, 18, tzinfo=UTC),
        physical_grid_export_kwh=3.973,
        physical_export_verified=True,
        bonus_pence=bonus,
        supplier_settled=False,
    )


def test_missing_bonus_is_unknown_not_fabricated_zero(monkeypatch) -> None:
    missing = _event(None)
    assert reporting._known_bonus_total([missing]) is None
    assert reporting._bonus_evidence_status([missing]) == "unvalued"
    assert reporting._bonus_evidence_status([]) == "no_completed_events"
    monkeypatch.setattr(reporting, "_today_completed_results", lambda: [missing])
    simulation = SimulationState(
        simulated_saving_session_bonus_pence=0.0,
        simulated_cost_pence=-200.0,
    )
    assert reporting._authoritative_today_bonus(simulation) is None
    assert reporting._reconcile_completed_credit(simulation) == simulation


def test_known_zero_and_partial_bonus_not_confused_with_missing() -> None:
    missing, zero, positive = _event(None), _event(0.0), _event(32.1)
    assert reporting._known_bonus_total([zero]) == 0.0
    assert reporting._known_bonus_total([missing, zero]) == 0.0
    assert reporting._bonus_evidence_status([missing, zero]) == "partial"
    assert reporting._known_bonus_total([missing, positive]) == 32.1
    assert reporting._bonus_evidence_status([positive]) == "complete"


def test_no_ungated_10_percent_house_floor_write() -> None:
    root = Path(__file__).parents[1] / "custom_components/kems"
    bridge = (root / "ohme_idle_household_bridge.py").read_text()
    backend = (root / "foxess_control_backend.py").read_text()
    assert "_EARLY_PAUSE_MARGIN_PERCENT = 3.5" in bridge
    assert "if bridge_paused_verified:" in backend
    assert "soc_for_house_floor" in backend
    assert "and ev_confirmed_unplugged" in backend
    assert "household_floor_transition" in backend
    assert "_async_wait_number" in backend
    assert "if not self._owned:" in bridge
    assert "post-pause mode and power readback" in bridge
