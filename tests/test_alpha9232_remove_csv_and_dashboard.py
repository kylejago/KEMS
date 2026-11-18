"""Regression for removing unused owner-local CSV diagnostics and old EV dashboard refs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def test_unused_local_supplier_csv_feature_is_absent() -> None:
    for relative in (
        "supplier_csv_import.py",
        "kems_core/supplier_meter_reconciliation.py",
    ):
        assert not (INTEGRATION / relative).exists()
    for relative in (
        "docs/supplier_meter_reconciliation.md",
        "tests/test_alpha9231_supplier_meter_reconciliation.py",
    ):
        assert not (ROOT / relative).exists()
    diagnostics = (INTEGRATION / "diagnostics.py").read_text()
    assert "historical_supplier_meter_reconciliation" not in diagnostics
    assert "read_local_supplier_csvs" not in diagnostics
    assert "historical_restart_gap_provenance" in diagnostics
    assert "historical_two_way_meter_gap_anchors" in diagnostics


def test_ev_dashboard_uses_kems_cheap_confirmation_not_legacy_dispatches() -> None:
    dashboard = (INTEGRATION / "kems_master_dashboard.yaml").read_text()
    assert "octopus_intelligent_tariff_octopus_intelligent" not in dashboard
    assert "plannedDispatches" not in dashboard
    assert "planned_dispatches" not in dashboard
    assert "binary_sensor.kems_cheap_period_confirmed" in dashboard
    assert "Extra daytime Intelligent slots" in dashboard
    assert "does not prove a discounted whole-home import rate" in dashboard
