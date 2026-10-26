"""Alpha9.143 — avoid duplicate settlement publications without stale control."""

from __future__ import annotations

from pathlib import Path

from kems_core.settlement_reconciliation_cadence import (
    settled_half_hour_snapshot,
    settled_half_hours_changed,
)

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def test_unchanged_settlements_do_not_require_second_publication() -> None:
    current = [
        {
            "start": "2026-10-26T15:30:00+00:00",
            "battery_export_kwh": 0.8,
            "energy": {"grid_export_kwh": 0.8},
        }
    ]
    captured = settled_half_hour_snapshot(current)
    assert not settled_half_hours_changed(captured, current)


def test_new_settled_half_hour_forces_same_scan_reconciliation() -> None:
    current = [{"start": "15:30", "battery_export_kwh": 0.8}]
    captured = settled_half_hour_snapshot(current)
    current.append({"start": "16:00", "battery_export_kwh": 1.0})
    assert settled_half_hours_changed(captured, current)


def test_corrected_half_hour_forces_same_scan_reconciliation() -> None:
    current = [{"start": "15:30", "energy": {"grid_export_kwh": 0.8}}]
    captured = settled_half_hour_snapshot(current)
    current[0]["energy"]["grid_export_kwh"] = 1.0
    assert captured[0]["energy"]["grid_export_kwh"] == 0.8
    assert settled_half_hours_changed(captured, current)


def test_removed_half_hour_forces_same_scan_reconciliation() -> None:
    current = [{"start": "15:30"}, {"start": "16:00"}]
    captured = settled_half_hour_snapshot(current)
    current.pop()
    assert settled_half_hours_changed(captured, current)


def test_precontrol_settlement_always_happens_before_control_planning() -> None:
    source = (KEMS / "coordinator.py").read_text()
    before = source.index("settled_before_shadow = settled_half_hour_snapshot(")
    first = source.index('detail_seconds["precontrol_settlement_reconciliation"]')
    plan = source.index("control = self._control.plan(")
    shadow = source.index("await self._shadow_validation.async_update(")
    second = source.index("if post_shadow_settlement_changed:")
    writer = source.index("foxess_control = await self._foxess_control.async_update(")
    assert before < first < plan < shadow < second < writer


def test_only_optional_second_publication_is_gated() -> None:
    source = (KEMS / "coordinator.py").read_text()
    assert (
        source.count("self._agile_smart_export.reconcile_current_day_settlements(") == 2
    )
    assert "if post_shadow_settlement_changed:" in source
    assert 'detail_seconds["postshadow_settlement_reconciliation"] = 0.0' in source
    assert "self._agile_smart_export.async_update(" in source
    assert "self._foxess_control.async_update(" in source
    guard = (KEMS / "update_maintenance_guard.py").read_text()
    assert "FoxESS control restoration pending" in guard


def test_diagnostic_profiles_show_safe_optimizer_and_reporting_boundaries() -> None:
    source = (KEMS / "coordinator.py").read_text()
    agile = (KEMS / "agile_smart_export.py").read_text()
    for token in (
        '"agile_manager_internal_seconds"',
        '"stage_detail_seconds"',
        '"post_shadow_settlement_changed"',
        '"precontrol_settlement_reconciliation"',
        '"lifetime_periods_and_roi"',
        '"power_down_reporting"',
    ):
        assert token in source
    for token in (
        '"historical_and_live_day_comparisons_seconds"',
        '"tomorrow_projection_seconds"',
        '"state_publication_seconds"',
    ):
        assert token in agile
    assert "await executor(self._compare_day, *compare_args)" in agile
