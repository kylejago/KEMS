"""Regression coverage for completed Agile Smart Export reporting."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"
DASHBOARD = ROOT / "dashboards" / "kems_agile_smart_export_builtin.yaml"
PACKAGED = (
    ROOT
    / "custom_components"
    / "kems"
    / "kems_agile_smart_export_dashboard.yaml"
)


def test_agile_runtime_exposes_coverage_gated_365_day_history() -> None:
    """A 12-month headline must never imply missing historical days exist."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "TWELVE_MONTH_DAYS = 365" in content
    assert 'periods["365_days"] = _aggregate(' in content
    assert 'period["complete_window"] = included >= expected' in content
    assert '"twelve_month_ready": bool(rolling.get("complete_window"))' in content
    assert 'winner = f"Collecting {rolling_days}/{TWELVE_MONTH_DAYS} days"' in content


def test_agile_runtime_publishes_same_dispatch_fixed_12p_benchmark() -> None:
    """Tariff value must be separable from dispatch-strategy value."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "sensor.kems_agile_vs_fixed_12p_gain_" in content
    assert "sensor.kems_fixed_12p_same_dispatch_income_" in content
    assert '"comparison_boundary": "same Agile Smart Export dispatch"' in content
    assert '"fixed_export_rate_pence": 12.0' in content


def test_agile_dashboard_surfaces_history_coverage_and_tariff_benchmark() -> None:
    """The managed UI must expose the new 365-day and tariff-only results."""
    content = DASHBOARD.read_text(encoding="utf-8")
    assert "sensor.kems_agile_history_coverage" in content
    assert "sensor.kems_full_kems_forecast_vs_agile_winner_365_days" in content
    assert "sensor.kems_agile_vs_fixed_12p_gain_365_days" in content
    assert "sensor.kems_agile_vs_fixed_12p_gain_today" in content
    assert "365/365 valid daily replays" in content


def test_packaged_agile_dashboard_matches_repository_source() -> None:
    """HACS must ship the exact Agile dashboard validated in the repository."""
    assert DASHBOARD.read_bytes() == PACKAGED.read_bytes()
