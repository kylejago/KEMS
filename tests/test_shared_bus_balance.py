"""Read-only shared-bus net-allocation evidence from existing KEMS readings."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kems_core.models import Snapshot
from kems_core.shared_bus_balance import assess_shared_bus_balance

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
AGES = {
    "house_load_kw": 10.0,
    "battery_power_kw": 10.0,
    "solar_power_kw": 10.0,
    "grid_import_kw": 10.0,
    "grid_export_kw": 10.0,
}


def _snapshot(**kwargs: object) -> Snapshot:
    payload = {
        "timestamp": NOW,
        "off_peak": True,
        "ev_connected": True,
        "ev_charging": True,
        "ev_power_kw": 6.0,
        "ev_power_age_seconds": 10.0,
        "ev_load_in_house_load": True,
        "house_load_kw": 8.0,
        "solar_power_kw": 0.0,
        "battery_power_kw": 2.0,
        "battery_soc": 75.0,
        "grid_import_kw": 6.0,
        "grid_export_kw": 0.0,
        "source_age_seconds": dict(AGES),
    }
    payload.update(kwargs)
    return Snapshot(**payload)


def _audit(snapshot: Snapshot, *, no_export: bool = True):
    return assess_shared_bus_balance(
        snapshot,
        no_paid_export_mode=no_export,
        battery_positive_is_discharge=True,
        inverter_limit_kw=7.0,
    )


def test_included_ev_measured_house_allowance_matches_grid_allocation() -> None:
    result = _audit(_snapshot())
    assert result.status == "net_allocation_consistent"
    assert result.site_load_kw == 8.0
    assert result.non_ev_house_kw == 2.0
    assert result.ev_power_kw == 6.0
    assert result.grid_requirement_shortfall_kw == 0.0
    assert result.battery_above_house_allowance_kw == 0.0
    assert result.candidate_inverter_site_output_ceiling_kw == 2.0
    assert result.hardware_write_authorised is False


def test_external_ev_counted_once_and_no_circuit_isolation_claim() -> None:
    result = _audit(_snapshot(house_load_kw=2.0, ev_load_in_house_load=False))
    assert result.status == "net_allocation_consistent"
    assert result.site_load_kw == 8.0
    assert result.non_ev_house_kw == 2.0
    assert "not circuit isolation" in result.reason


def test_battery_serving_ev_detected_from_existing_power_balance() -> None:
    result = _audit(_snapshot(battery_power_kw=5.0, grid_import_kw=3.0))
    assert result.status == "deviation"
    assert result.battery_above_house_allowance_kw == 3.0
    assert result.grid_requirement_shortfall_kw == 3.0
    assert result.hardware_write_authorised is False


def test_pv_surplus_cannot_be_falsely_reported_as_battery_for_ev() -> None:
    result = _audit(
        _snapshot(solar_power_kw=3.0, battery_power_kw=0.0, grid_import_kw=5.0)
    )
    assert result.status == "net_allocation_consistent"
    assert result.house_battery_allowance_kw == 0.0
    assert result.conservative_ev_grid_requirement_kw == 5.0


def test_unknown_ev_measurement_scope_refuses_attribution() -> None:
    result = _audit(_snapshot(ev_load_in_house_load=None))
    assert result.status == "unavailable"
    assert result.non_ev_house_kw is None


def test_aged_ohme_report_cannot_validate_shared_bus() -> None:
    assert _audit(_snapshot(ev_power_age_seconds=None)).status == "unavailable"
    assert _audit(_snapshot(ev_power_age_seconds=91.0)).status == "unavailable"


def test_stale_or_undated_readings_fail_closed() -> None:
    assert _audit(_snapshot(stale_fields=("battery_power_kw",))).status == "unavailable"
    assert _audit(_snapshot(source_age_seconds={})).status == "unavailable"
    old = dict(AGES, house_load_kw=181.0)
    assert _audit(_snapshot(source_age_seconds=old)).status == "unavailable"


def test_unknown_or_inconsistent_ev_state_does_not_look_valid() -> None:
    assert _audit(_snapshot(ev_charging=None)).status == "unavailable"
    assert _audit(_snapshot(ev_charging=False)).status == "unavailable"
    assert _audit(_snapshot(ev_power_kw=None)).status == "unavailable"
    assert _audit(_snapshot(ev_charging=False, ev_power_kw=0.0)).status == "idle"


def test_paid_export_mode_remains_outside_no_export_audit() -> None:
    assert _audit(_snapshot(), no_export=False).status == "not_applicable"


def test_audit_persists_with_snapshot_and_has_no_write_path() -> None:
    result = _audit(_snapshot())
    persisted = Snapshot.from_dict(
        Snapshot(shared_bus_ev_audit=result.to_dict()).to_dict()
    )
    assert persisted.shared_bus_ev_audit["status"] == "net_allocation_consistent"
    assert persisted.shared_bus_ev_audit["hardware_write_authorised"] is False

    source = (ROOT / "kems_core" / "shared_bus_balance.py").read_text(encoding="utf-8")
    assert "async_call(" not in source
    assert "set_value(" not in source
    assert "select_option(" not in source
    assert "hardware_write_authorised: bool = False" in source
    assert "snapshot.shared_bus_ev_audit = assess_shared_bus_balance(" in (
        ROOT / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert '"shared_bus_ev_balance": dict(data.snapshot.shared_bus_ev_audit)' in (
        ROOT / "diagnostics.py"
    ).read_text(encoding="utf-8")
    assert 'key="shared_bus_ev_balance"' in (ROOT / "sensor.py").read_text(
        encoding="utf-8"
    )
