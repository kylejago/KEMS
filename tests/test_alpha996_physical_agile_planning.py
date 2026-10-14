"""Alpha9.96: live Agile planning follows physical, not digital-twin, SOC."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

from kems_core import ControlConfig, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import physical_energy_evidence_matches_snapshot
from kems_core.agile_physical_energy import PaidAgilePhysicalEnergyTracker

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 10, 14, 12, 47, 4, tzinfo=UTC)
SIM = SimulationConfig(
    battery_capacity_kwh=56.42,
    battery_reserve_percent=15.0,
    discharge_efficiency=0.95,
    max_discharge_kw=7.0,
)
CONTROL = ControlConfig(stale_data_seconds=180)


def _load_physical_planning():
    """Load the HA-free adapter with the real KEMS pure core."""
    package_name = "kems_alpha996_physical_planning_test"
    package = ModuleType(package_name)
    package.__path__ = [str(ROOT)]
    sys.modules[package_name] = package
    import kems_core

    sys.modules[f"{package_name}.kems_core"] = kems_core
    sys.modules[f"{package_name}.kems_core.agile_live_reserve"] = sys.modules[
        "kems_core.agile_live_reserve"
    ]
    target = f"{package_name}.agile_physical_planning"
    spec = importlib.util.spec_from_file_location(
        target, ROOT / "agile_physical_planning.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[target] = module
    spec.loader.exec_module(module)
    return module


planning = _load_physical_planning()


def _scan(at: datetime, soc_at: datetime, **changes: object) -> Snapshot:
    fields = dict(
        timestamp=at,
        battery_soc=100.0,
        battery_power_kw=0.0,
        house_load_kw=0.75,
        solar_power_kw=2.0,
        source_age_seconds={
            "battery_soc": (at - soc_at).total_seconds(),
            "battery_power_kw": 2.0,
            "house_load_kw": 2.0,
            "solar_power_kw": 2.0,
        },
        source_data_age_seconds=2.0,
        next_offpeak_start=at + timedelta(hours=10),
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=6.0,
    )
    fields.update(changes)
    return Snapshot(**fields)


def _manager(snapshot: Snapshot, evidence) -> SimpleNamespace:
    return SimpleNamespace(
        _kems_physical_planning_context={
            "snapshot": snapshot,
            "evidence": evidence,
            "control": CONTROL,
        }
    )


def _working_evidence() -> tuple[Snapshot, object]:
    tracker = PaidAgilePhysicalEnergyTracker()
    anchor_time = NOW - timedelta(minutes=7)
    previous = _scan(anchor_time, anchor_time - timedelta(seconds=5))
    tracker.observe(previous, SIM, CONTROL, now=anchor_time)
    middle_time = NOW - timedelta(minutes=1)
    tracker.observe(
        _scan(middle_time, anchor_time - timedelta(seconds=5)),
        SIM,
        CONTROL,
        now=middle_time,
    )
    snap = _scan(NOW, anchor_time - timedelta(seconds=5))
    evidence = tracker.observe(snap, SIM, CONTROL, now=NOW)
    assert evidence.lower_bound_kwh is not None
    return snap, evidence


def test_physical_100_percent_reconciles_live_budget_above_74_5_percent_twin() -> None:
    snap, evidence = _working_evidence()
    assert physical_energy_evidence_matches_snapshot(evidence, snap, CONTROL, now=NOW)
    physical_soc, proof = planning.physical_planning_soc(
        _manager(snap, evidence), now=NOW, config=SIM
    )
    assert physical_soc is not None
    assert 97.0 < physical_soc < 100.0
    assert physical_soc > 74.457
    assert proof["available"] is True
    assert proof["physical_energy_lower_bound_kwh"] > 54.0
    assert proof["replay_simulation_soc_preserved"] is True
    physical_export_budget = (
        (physical_soc - 15.0)
        / 100.0
        * SIM.battery_capacity_kwh
        * SIM.discharge_efficiency
    )
    twin_export_budget = (
        (74.457 - 15.0) / 100.0 * SIM.battery_capacity_kwh * SIM.discharge_efficiency
    )
    assert physical_export_budget > twin_export_budget + 11.0


def test_missing_restart_or_expired_proof_does_not_create_physical_authority() -> None:
    snap, evidence = _working_evidence()
    for manager, at in (
        (SimpleNamespace(), NOW),
        (_manager(snap, None), NOW),
        (_manager(snap, evidence), NOW + timedelta(minutes=1)),
    ):
        result, proof = planning.physical_planning_soc(manager, now=at, config=SIM)
        assert result is None
        assert proof["available"] is False


def test_sensor_conflicts_stale_power_and_changed_soc_fail_closed() -> None:
    snap, evidence = _working_evidence()
    cases = (
        _scan(NOW, NOW - timedelta(minutes=7), battery_soc=99.0),
        _scan(NOW, NOW - timedelta(minutes=7), battery_power_kw=None),
        _scan(NOW, NOW - timedelta(minutes=7), stale_fields=("battery_soc",)),
        _scan(NOW, NOW - timedelta(minutes=7), stale_fields=("battery_power_kw",)),
        _scan(NOW, NOW - timedelta(minutes=7), source_data_age_seconds=181.0),
        _scan(NOW, NOW - timedelta(minutes=20)),
        _scan(NOW, NOW - timedelta(minutes=7), off_peak=True),
    )
    for invalid in cases:
        bound, diagnostic = planning.physical_planning_soc(
            _manager(invalid, evidence), now=NOW, config=SIM
        )
        assert bound is None, diagnostic
        assert diagnostic["available"] is False


def test_capacity_mismatch_and_invalid_physical_values_cannot_grant_export() -> None:
    snap, evidence = _working_evidence()
    smaller = SimulationConfig(
        battery_capacity_kwh=40.0,
        battery_reserve_percent=15.0,
        discharge_efficiency=0.95,
    )
    physical_soc, diagnostic = planning.physical_planning_soc(
        _manager(snap, evidence), now=NOW, config=smaller
    )
    assert physical_soc is None
    assert diagnostic["available"] is False


def test_rolling_chain_uses_planning_soc_for_discharge_forecast_and_hard_floor() -> (
    None
):
    """Keep simulation independent while routing live dispatch through one basis."""
    rolling = (ROOT / "agile_rolling_replan_runtime.py").read_text()
    deadline = (ROOT / "agile_deadline_guard_runtime.py").read_text()
    total = (ROOT / "agile_total_discharge_ledger.py").read_text()
    forecast = (ROOT / "agile_forecast_path_scheduler.py").read_text()
    floor = (ROOT / "agile_safety_floor.py").read_text()
    coordinator = (ROOT / "coordinator.py").read_text()
    assert "physical_planning_soc(self, now=now, config=config)" in rolling
    assert '"planning_soc_percent": round(soc, 3)' in rolling
    assert '"simulated_soc_percent": round(' in rolling
    assert "install_physical_deadline_reconciliation()" in floor
    physical_deadline = (ROOT / "agile_physical_deadline_reconciliation.py").read_text()
    assert "deadline_runtime._deadline_guard_context" in physical_deadline
    assert 'plan.get("planning_soc_percent")' in total
    assert 'plan.get("planning_soc_percent")' in forecast
    assert 'plan.get("planning_soc_percent")' in floor
    assert "self._agile_smart_export._kems_physical_planning_context" in coordinator
    assert coordinator.index("self._paid_agile_physical_energy.observe(") < (
        coordinator.index("await self._agile_smart_export.async_update(")
    )
    assert "guard_paid_agile_physical_export(" in coordinator
    assert (
        '"scope": "paid_agile_live_control_only"'
        in (ROOT / "agile_physical_planning.py").read_text()
    )


def test_legacy_cheap_charge_and_no_paid_export_always_exclude_physical_planner() -> (
    None
):
    coordinator = (ROOT / "coordinator.py").read_text()
    assert "selected_export_tariff == EXPORT_TARIFF_TYPE_AGILE" in coordinator
    assert 'self.settings.control.operating_mode == "control"' in coordinator
    assert "not snapshot.cheap_period_confirmed" in coordinator
    assert "not snapshot.saving_session_active" in coordinator
    assert "self._paid_agile_physical_energy.reset()" in coordinator
