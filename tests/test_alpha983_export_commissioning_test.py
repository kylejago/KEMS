"""Alpha9.83 manual export commissioning and ROI-neutrality regressions."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlState, SimulationState

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
COORDINATOR = KEMS / "coordinator.py"
SWITCH = KEMS / "switch.py"
DIAGNOSTICS = KEMS / "diagnostics.py"


class _Store:
    """Tiny HA Store stand-in for deterministic unit tests."""

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, *args, **kwargs):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


def _load_module():
    package_name = "alpha983_export_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(KEMS)]
    sys.modules[package_name] = package

    const = types.ModuleType(f"{package_name}.const")
    const.DOMAIN = "kems"
    const.STORAGE_NAMESPACE = "test"
    sys.modules[const.__name__] = const

    core = types.ModuleType(f"{package_name}.kems_core")
    core.ControlConfig = ControlConfig
    core.ControlState = ControlState
    core.SimulationState = SimulationState
    sys.modules[core.__name__] = core

    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    if not hasattr(homeassistant, "__path__"):
        homeassistant.__path__ = []
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    if not hasattr(helpers, "__path__"):
        helpers.__path__ = []
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = _Store
    sys.modules["homeassistant.helpers.storage"] = storage

    module_name = f"{package_name}.export_commissioning_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        KEMS / "export_commissioning_test.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _control(**overrides: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "awaiting_export_tariff",
        "desired_work_mode": "Self Use",
        "desired_battery_to_home_power_kw": 0.8,
        "desired_battery_export_power_kw": 0.0,
        "desired_total_discharge_power_kw": 0.8,
        "desired_min_soc_percent": 10.0,
        "desired_grid_export_allowed": False,
        "grid_available": True,
        "island_mode_active": False,
        "data_fresh": True,
        "plan_safe": True,
        "control_enabled": True,
        "commissioned": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(overrides)
    return ControlState(**values)


def _snapshot(now: datetime, **overrides: object):
    values: dict[str, object] = {
        "timestamp": now,
        "stale_fields": (),
        "cheap_period_confirmed": False,
        "saving_session_active": False,
        "ev_connected": False,
        "ev_charging": False,
        "ev_power_kw": 0.0,
        "ev_power_age_seconds": 1.0,
        "battery_soc": 80.0,
        "solar_power_kw": 0.0,
        "grid_export_kw": 0.0,
        "grid_import_kw": 0.0,
        "battery_power_kw": 0.8,
        "current_import_rate": 37.1715,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _agile(target_kw: float = 5.6) -> dict[str, object]:
    return {
        "rolling_export_plan": {
            "available": True,
            "current_battery_export_target_kw": target_kw,
        }
    }


def test_manual_test_requires_no_paid_export_and_positive_agile_target() -> None:
    module = _load_module()
    now = datetime(2026, 10, 8, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")

    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now),
            control=_control(),
            agile_state=_agile(),
            no_paid_export_mode=False,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )

    assert started is False
    assert "No paid export" in reason


def test_commissioning_rejects_solar_above_near_zero_debt_envelope() -> None:
    """Avoid treating solar-attributable grid export as battery recharge debt."""
    module = _load_module()
    now = datetime(2026, 10, 8, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now, solar_power_kw=0.05),
            control=_control(),
            agile_state=_agile(),
            no_paid_export_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started is False
    assert "0.01 kW" in reason
    assert module._MAX_PROOF_SOLAR_KW == 0.01


def test_proof_is_exactly_1kw_then_stress_follows_live_agile_target() -> None:
    module = _load_module()
    now = datetime(2026, 10, 8, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    snapshot = _snapshot(now)
    control = _control()
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10.0,
        max_discharge_kw=7.0,
        export_limit_kw=6.4,
        inverter_limit_kw=7.0,
    )

    started, _ = asyncio.run(
        controller.async_start(
            snapshot=snapshot,
            control=control,
            agile_state=_agile(5.6),
            no_paid_export_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started is True

    proof, promoted = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(5.6),
            config=config,
            backend_status={"paid_export_live_proven": False},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert promoted is False
    assert proof.operating_reason == "export_commissioning_proof"
    assert proof.desired_battery_export_power_kw == 1.0
    assert proof.desired_min_soc_percent == 15.0
    assert proof.desired_grid_export_allowed is True

    stress, promoted = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(5.6),
            config=config,
            backend_status={"paid_export_live_proven": True},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert promoted is True
    assert stress.operating_reason == "export_commissioning_agile_stress"
    assert stress.desired_battery_export_power_kw == 5.6
    assert stress.desired_total_discharge_power_kw == 6.4


def test_roi_exclusion_does_not_hide_physical_energy_or_import_cost() -> None:
    module = _load_module()
    now = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    controller._roi_excluded_recharge_cost_pence_by_date = {"2026-10-08": 4.2}
    simulation = SimulationState(
        ready=True,
        actual_grid_import_kwh=12.3,
        actual_grid_export_kwh=0.12,
        actual_import_cost_pence=250.0,
        actual_export_income_pence=0.0,
        actual_avoided_import_value_pence=100.0,
        actual_system_value_pence=100.0,
    )

    adjusted = controller.roi_adjusted_simulation(simulation, now)

    assert adjusted.actual_grid_import_kwh == 12.3
    assert adjusted.actual_grid_export_kwh == 0.12
    assert adjusted.actual_import_cost_pence == 250.0
    assert adjusted.actual_export_income_pence == 0.0
    assert adjusted.actual_avoided_import_value_pence == 104.2
    assert adjusted.actual_system_value_pence == 104.2


def test_backend_keeps_real_tariff_no_paid_but_opens_only_test_surface() -> None:
    source = BACKEND.read_text(encoding="utf-8")

    assert "commissioning_export_test: bool = False" in source
    assert "commissioning_export_test or not no_paid_export_mode" in source
    assert "no_paid_export_mode and not commissioning_export_test" in source
    assert (
        'required_keys.extend(("force_discharge_power", "export_power_limit"))'
        in source
    )
    assert "if force_restore:" in source
    assert "Export commissioning requested verified FoxESS restoration" in source
    assert '"import_power_limit_write": "never_written_by_alpha9.83"' in source


def test_coordinator_uses_manual_switch_timeout_and_roi_only_adjustment() -> None:
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    switch = SWITCH.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")

    assert "ExportCommissioningTestController" in coordinator
    assert "EXPORT_TARIFF_TYPE_NONE" in coordinator
    assert "_schedule_export_commissioning_timeout" in coordinator
    assert "stress_seconds" in coordinator
    assert "commissioning_export_test=(" in coordinator
    assert (
        "force_restore=self._export_commissioning_test.restore_requested" in coordinator
    )
    assert "roi_adjusted_simulation" in coordinator
    assert (
        "whole_home = self._whole_home.summarise(snapshot, simulation, gas)"
        in coordinator
    )
    assert "KEMSExportCommissioningTestSwitch" in switch
    assert '_attr_name = "Export commissioning test"' in switch
    assert (
        '"export_commissioning_test": coordinator.export_commissioning_test_state'
        in diagnostics
    )


def test_financial_contract_is_zero_income_and_recharge_cost_only() -> None:
    source = (KEMS / "export_commissioning_test.py").read_text(encoding="utf-8")

    assert '"export_income_policy": (' in source
    assert '"normal_live_agile_interval_settlement"' in source
    assert '"zero_no_paid_export"' in source
    assert '"physical_energy_history": "retained"' in source
    assert '"actual_roi_policy": (' in source
    assert '"exclude_test_recharge_cost"' in source
    assert '"normal_paid_agile_accounting"' in source
    assert (
        "actual_import_cost_pence"
        not in source.split("def roi_adjusted_simulation", 1)[1]
    )
    assert "actual_avoided_import_value_pence" in source
    assert "actual_system_value_pence" in source


def test_solar_repayment_clears_debt_without_financial_exclusion() -> None:
    module = _load_module()
    controller = module.ExportCommissioningTestController(object(), "entry")
    start = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    controller._recharge_debt_stored_kwh = 0.1
    controller._last_recharge_observation_at = start
    snapshot = _snapshot(
        start.replace(minute=1),
        cheap_period_confirmed=False,
        battery_power_kw=-1.0,
        grid_import_kw=0.0,
    )
    config = types.SimpleNamespace(
        battery_power_positive_is_discharge=True,
        charge_efficiency=0.95,
    )

    asyncio.run(controller.async_observe_snapshot(snapshot, snapshot.timestamp, config))

    assert controller._recharge_debt_stored_kwh < 0.1
    assert controller._roi_excluded_recharge_cost_pence_by_date == {}


def test_cheap_grid_repayment_creates_only_roi_recharge_exclusion() -> None:
    module = _load_module()
    controller = module.ExportCommissioningTestController(object(), "entry")
    start = datetime(2026, 10, 9, 23, 30, tzinfo=UTC)
    controller._recharge_debt_stored_kwh = 0.1
    controller._last_recharge_observation_at = start
    snapshot = _snapshot(
        start.replace(minute=31),
        cheap_period_confirmed=True,
        battery_power_kw=-1.0,
        grid_import_kw=2.0,
        current_import_rate=8.0,
    )
    config = types.SimpleNamespace(
        battery_power_positive_is_discharge=True,
        charge_efficiency=0.95,
    )

    asyncio.run(controller.async_observe_snapshot(snapshot, snapshot.timestamp, config))

    assert controller._recharge_debt_stored_kwh < 0.1
    assert controller._roi_excluded_recharge_cost_pence_by_date["2026-10-09"] > 0


def test_zero_simulated_agile_target_uses_bounded_physical_commissioning() -> None:
    """A depleted simulation must not impersonate the healthy physical battery."""
    module = _load_module()
    now = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    snapshot = _snapshot(now, battery_soc=82.0)
    control = _control()
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10.0,
        max_discharge_kw=7.0,
        export_limit_kw=6.4,
        inverter_limit_kw=7.0,
    )
    started, _ = asyncio.run(
        controller.async_start(
            snapshot=snapshot,
            control=control,
            agile_state=_agile(0.0),
            no_paid_export_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started is True
    proof, _ = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(0.0),
            config=config,
            backend_status={"paid_export_live_proven": False},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert proof.desired_battery_export_power_kw == 1.0
    stress, promoted = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(0.0),
            config=config,
            backend_status={"paid_export_live_proven": True},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert promoted is True
    assert stress.desired_battery_export_power_kw == 1.0
    assert "bounded physical export" in stress.next_action


def test_missing_agile_plan_still_fails_closed() -> None:
    module = _load_module()
    now = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now),
            control=_control(),
            agile_state={},
            no_paid_export_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started is False
    assert "unavailable" in reason


def test_live_agile_target_zero_during_stress_requests_safe_restore() -> None:
    """A previously positive plan must not silently become physical-only."""
    module = _load_module()
    now = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    snapshot = _snapshot(now)
    control = _control()
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10.0,
        max_discharge_kw=7.0,
        export_limit_kw=6.4,
        inverter_limit_kw=7.0,
    )
    started, _ = asyncio.run(
        controller.async_start(
            snapshot=snapshot,
            control=control,
            agile_state=_agile(5.6),
            no_paid_export_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started
    _, promoted = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(5.6),
            config=config,
            backend_status={"paid_export_live_proven": True},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert promoted
    result, _ = asyncio.run(
        controller.async_control_override(
            control=control,
            snapshot=snapshot,
            agile_state=_agile(0.0),
            config=config,
            backend_status={"paid_export_live_proven": True},
            no_paid_export_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert result is control
    assert controller._restore_requested is True
    assert controller._command_target_kw == 0.0


def test_paid_agile_manual_test_starts_without_changing_selected_tariff() -> None:
    module = _load_module()
    now = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now),
            control=_control(),
            agile_state=_agile(5.6),
            no_paid_export_mode=False,
            paid_agile_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started, reason
    state = controller.status
    assert state["real_export_tariff"] == "Agile Outgoing"
    assert state["export_income_policy"] == "normal_live_agile_interval_settlement"
    assert state["actual_roi_policy"] == "normal_paid_agile_accounting"
    assert state["stage"] == "proof"
    assert state["proof_target_kw"] == 1.0
    assert controller._store.data["paid_agile_session"] is True

    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10.0,
        max_discharge_kw=7.0,
        export_limit_kw=7.0,
        inverter_limit_kw=7.0,
    )
    control, promoted = asyncio.run(
        controller.async_control_override(
            control=_control(),
            snapshot=_snapshot(now),
            agile_state=_agile(5.6),
            config=config,
            backend_status={"paid_export_live_proven": False},
            no_paid_export_mode=False,
            paid_agile_mode=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert not promoted
    assert control.operating_reason == "export_commissioning_proof"
    assert control.desired_battery_export_power_kw == 1.0
    assert control.desired_total_discharge_power_kw == 1.8
    assert control.desired_min_soc_percent >= 15.0
    assert control.desired_total_discharge_power_kw <= config.max_discharge_kw


def test_paid_agile_test_restores_when_user_changes_export_tariff() -> None:
    module = _load_module()
    now = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    original = _control()
    snapshot = _snapshot(now)
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=snapshot,
            control=original,
            agile_state=_agile(),
            no_paid_export_mode=False,
            paid_agile_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started, reason
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10,
        max_discharge_kw=7,
        export_limit_kw=7,
        inverter_limit_kw=7,
    )
    returned, promoted = asyncio.run(
        controller.async_control_override(
            control=original,
            snapshot=snapshot,
            agile_state=_agile(),
            config=config,
            backend_status={},
            no_paid_export_mode=True,
            paid_agile_mode=False,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert returned is original
    assert not promoted
    assert controller.restore_requested
    assert controller.status["stage"] == "restoring"
    assert controller.status["command_target_kw"] == 0.0
    assert "tariff changed" in controller.status["stop_reason"]


def test_manual_paid_agile_rejects_unsafe_start_conditions() -> None:
    module = _load_module()
    now = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    unsafe = (
        (_snapshot(now, solar_power_kw=0.05), "0.01 kW"),
        (_snapshot(now, ev_connected=None), "Ohme"),
        (_snapshot(now, cheap_period_confirmed=True), "cheap period"),
        (_snapshot(now, battery_soc=19.0), "at least 20%"),
        (_snapshot(now, stale_fields=("grid_export_kw",)), "stale"),
    )
    for snapshot, message in unsafe:
        controller = module.ExportCommissioningTestController(object(), "entry")
        started, reason = asyncio.run(
            controller.async_start(
                snapshot=snapshot,
                control=_control(),
                agile_state=_agile(),
                no_paid_export_mode=False,
                paid_agile_mode=True,
                technical_ready=True,
                emergency_stop=False,
                ev_hold_active=False,
                now=now,
            )
        )
        assert not started
        assert message in reason
        assert not controller.active

    for no_paid, paid in ((False, False), (True, True)):
        controller = module.ExportCommissioningTestController(object(), "entry")
        started, reason = asyncio.run(
            controller.async_start(
                snapshot=_snapshot(now),
                control=_control(),
                agile_state=_agile(),
                no_paid_export_mode=no_paid,
                paid_agile_mode=paid,
                technical_ready=True,
                emergency_stop=False,
                ev_hold_active=False,
                now=now,
            )
        )
        assert not started
        assert "No paid export or Agile Outgoing" in reason


def test_paid_agile_test_uses_normal_roi_and_does_not_create_unpaid_debt() -> None:
    module = _load_module()
    now = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now),
            control=_control(),
            agile_state=_agile(),
            no_paid_export_mode=False,
            paid_agile_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started, reason
    controller._exported_kwh = 0.23
    controller._peak_grid_export_kw = 0.9
    simulation = SimulationState(
        ready=True,
        actual_grid_import_kwh=3.5,
        actual_grid_export_kwh=0.23,
        actual_import_cost_pence=140.0,
        actual_export_income_pence=5.808,
        actual_avoided_import_value_pence=105.0,
        actual_system_value_pence=110.808,
    )
    assert controller.roi_adjusted_simulation(simulation, now) is simulation
    controller._successful_completion_requested = True
    asyncio.run(controller._async_finalize(now=now, config=ControlConfig()))
    assert controller._recharge_debt_stored_kwh == 0.0
    last = controller.status["history"][-1]
    assert last["completed_successfully"] is True
    assert last["paid_agile_session"] is True
    assert last["roi_included"] is True
    assert last["export_income_pence"] is None
    assert last["export_income_policy"] == "normal_live_agile_interval_settlement"
    assert not controller.active


def test_paid_agile_session_restart_restores_without_resuming_export() -> None:
    module = _load_module()
    now = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    controller = module.ExportCommissioningTestController(object(), "entry")
    started, reason = asyncio.run(
        controller.async_start(
            snapshot=_snapshot(now),
            control=_control(),
            agile_state=_agile(),
            no_paid_export_mode=False,
            paid_agile_mode=True,
            technical_ready=True,
            emergency_stop=False,
            ev_hold_active=False,
            now=now,
        )
    )
    assert started, reason
    stored = dict(controller._store.data)
    assert stored["active"]
    assert stored["paid_agile_session"]
    reloaded = module.ExportCommissioningTestController(object(), "entry")
    reloaded._store.data = stored
    asyncio.run(reloaded.async_load())
    assert reloaded.restore_requested
    assert not reloaded.hardware_authority_active
    assert reloaded.status["stage"] == "restoring"
    assert reloaded.status["real_export_tariff"] == "Agile Outgoing"


def test_paid_agile_commissioning_remains_opt_in_and_normal_ledger_owned() -> None:
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    test = (KEMS / "export_commissioning_test.py").read_text(encoding="utf-8")
    switch = SWITCH.read_text(encoding="utf-8")
    assert (
        "paid_agile_mode=selected_export_tariff == EXPORT_TARIFF_TYPE_AGILE"
        in coordinator
    )
    assert "paid_agile_mode=tariff_type == EXPORT_TARIFF_TYPE_AGILE" in coordinator
    assert "actual_export_income_pence(" in coordinator
    assert "revalue_actual_export_income(" in coordinator
    assert "normal_live_agile_interval_settlement" in test
    assert "if not self._paid_agile_session:" in test
    assert "self._paid_agile_session != paid_agile_mode" in test
    assert '"manual_start_only": True' in switch
    assert '"Agile Outgoing"' in switch
