"""Regression coverage for alpha7.19 validation and shadow-control milestone."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
VALIDATION = ROOT / "custom_components" / "kems" / "agile_alpha719_validation.py"
DASHBOARD = ROOT / "custom_components" / "kems" / "agile_alpha719_dashboard.py"
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"
COORDINATOR = ROOT / "custom_components" / "kems" / "coordinator.py"
SHADOW = ROOT / "custom_components" / "kems" / "shadow_validation.py"


def test_fixed_window_winners_require_complete_evidence() -> None:
    source = VALIDATION.read_text(encoding="utf-8")
    assert 'for key in ("7_days", "30_days", "365_days")' in source
    assert 'f"Collecting {included}/{expected} days"' in source
    assert 'period["authoritative"] = complete' in source
    assert 'period["partial_comparison"] = dict(comparison)' in source
    assert '"agile_advantage_pence": None' in source


def test_backfill_diagnostics_use_actual_hourly_replay_resolution() -> None:
    source = VALIDATION.read_text(encoding="utf-8")
    assert '"period": "hour"' in source
    assert "sensor.kems_agile_backfill_source_map" in source
    assert '"logical_sources": logical' in source
    assert '"missing_prerequisites": missing' in source
    assert '"direct_path_ready": not missing' in source


def test_agile_validation_exposes_soc_trajectory_and_decision_audit() -> None:
    source = VALIDATION.read_text(encoding="utf-8")
    assert "sensor.kems_agile_soc_trajectory" in source
    assert "sensor.kems_agile_projected_soc_at_deadline" in source
    assert "sensor.kems_agile_overnight_recharge_target" in source
    assert "sensor.kems_agile_decision_audit" in source
    assert '"source": "rolling_replan_conservative"' in source
    assert "Future solar is not pre-spent" in source


def test_shadow_validation_runs_after_control_plan_every_scan() -> None:
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    assert "ShadowValidationRecorder(hass, entry.entry_id)" in coordinator
    assert "await self._shadow_validation.async_load()" in coordinator
    assert "control = self._control.plan(" in coordinator
    assert "await self._shadow_validation.async_update(" in coordinator
    assert "await self._shadow_validation.async_shutdown()" in coordinator


def test_shadow_runtime_is_audited_but_never_writes_hardware() -> None:
    source = SHADOW.read_text(encoding="utf-8")
    assert '"hardware_writes": "blocked"' in source
    assert '"real_backend_available": False' in source
    forbidden = (
        "foxess_modbus.write",
        "async_write_ha_state",
        'hass.services.async_call("foxess',
        "hass.services.async_call('foxess',",
    )
    assert not any(value in source.lower() for value in forbidden)


def test_alpha719_dashboard_keeps_eleven_page_navigation_and_adds_cards() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert '_inject_after_cards(content, "live", _LIVE_CARD)' in source
    assert '_inject_after_cards(content, "plan", _PLAN_CARD)' in source
    assert '_inject_after_cards(content, "agile", _AGILE_CARDS)' in source
    assert '_inject_after_cards(content, "history", _HISTORY_CARD)' in source
    assert '_inject_after_cards(content, "control", _CONTROL_CARDS)' in source
    assert "Actual → Target → Difference readiness" in source
    assert "Shadow-control validation" in source


def test_alpha719_install_order_preserves_final_dashboard_compositor() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert (
        "install_alpha717_dashboard_patch()\ninstall_alpha719_validation_patch()"
        in source
    )
    assert (
        "install_alpha719_validation_patch()\n"
        "install_dashboard_consolidation()\n"
        "install_alpha719_dashboard_patch()"
    ) in source
