"""Regress Alpha9.116 maintenance deferral across active energy sessions."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "custom_components/kems/update_maintenance_guard.py"
UPDATE = ROOT / "custom_components/kems/update_orchestrator.py"
spec = importlib.util.spec_from_file_location(
    "kems_update_maintenance_guard_test", MODULE
)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
NOW = datetime(2026, 10, 18, 5, 59, tzinfo=UTC)


def _snapshot(*, now=NOW, **kwargs):
    values = {
        "timestamp": now,
        "saving_session_active": False,
        "cheap_period_confirmed": False,
        "ev_power_kw": 0.0,
        "battery_power_kw": 1.0,
        "grid_export_kw": 0.0,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def _check(
    *,
    now=NOW,
    snapshot=None,
    happy_hour=None,
    power_down=None,
    foxess=None,
    rolling_export=None,
    states=None,
):
    return guard.maintenance_energy_blockers(
        now=now,
        snapshot=_snapshot(now=now) if snapshot is None else snapshot,
        happy_hour=happy_hour or {},
        power_down=power_down or {},
        foxess=foxess or {},
        rolling_export=rolling_export or {},
        states=states or {},
    )


def test_idle_daytime_home_discharge_is_safe() -> None:
    assert _check() == []


def test_reward_hour_guard_before_during_and_after() -> None:
    start = NOW + timedelta(minutes=10)
    end = start + timedelta(hours=1)
    plan = {"start": start.isoformat(), "end": end.isoformat()}
    assert "Happy Hour" in " ".join(_check(happy_hour=plan))
    assert "Happy Hour" in " ".join(
        _check(now=start + timedelta(minutes=30), happy_hour=plan)
    )
    assert "Happy Hour" in " ".join(
        _check(now=end + timedelta(minutes=4), happy_hour=plan)
    )
    assert _check(now=end + timedelta(minutes=6), happy_hour=plan) == []
    assert _check(now=start - timedelta(minutes=16), happy_hour=plan) == []


def test_power_down_active_and_imminent_are_blockers() -> None:
    assert "Power Down" in " ".join(_check(power_down={"active": True}))
    assert "Power Down" in " ".join(
        _check(snapshot=_snapshot(saving_session_active=True))
    )
    states = {
        "next_power_down_start": (NOW + timedelta(minutes=14)).isoformat(),
        "next_power_down_end": (NOW + timedelta(hours=1)).isoformat(),
    }
    assert "Power Down" in " ".join(_check(states=states))
    assert "Power Down" in " ".join(
        _check(states={"next_power_down_start": states["next_power_down_start"]})
    )


def test_intelligent_and_cheap_windows_are_protected() -> None:
    assert "Octopus" in " ".join(_check(states={"off_peak": "on"}))
    assert "Octopus" in " ".join(_check(states={"intelligent_slot": "on"}))
    assert "cheap" in " ".join(_check(snapshot=_snapshot(cheap_period_confirmed=True)))
    assert "Cheap" in " ".join(
        _check(
            states={
                "next_off_peak_start": (NOW + timedelta(minutes=8)).isoformat(),
            }
        )
    )


def test_ev_forced_charge_export_and_restore_block_maintenance() -> None:
    assert "EV" in " ".join(_check(snapshot=_snapshot(ev_power_kw=4.0)))
    assert "EV" in " ".join(_check(states={"ev_charging": "on"}))
    assert "FoxESS" in " ".join(_check(foxess={"decision_action": "force_charge"}))
    assert "FoxESS" in " ".join(_check(foxess={"decision_action": "force_discharge"}))
    assert "restoration" in " ".join(
        _check(foxess={"commissioning_restore_pending": True})
    )
    assert "Inverter" in " ".join(
        _check(states={"foxess_work_mode": "Force Discharge"})
    )


def test_physical_battery_charge_export_but_not_home_discharge() -> None:
    assert "battery charging" in " ".join(
        _check(snapshot=_snapshot(battery_power_kw=-3.0))
    )
    assert "battery export" in " ".join(
        _check(snapshot=_snapshot(battery_power_kw=4.0, grid_export_kw=3.0))
    )
    assert not _check(snapshot=_snapshot(battery_power_kw=3.0, grid_export_kw=0.0))


def test_rolling_physical_agile_export_intent_is_protected() -> None:
    plan = {"current_battery_export_target_kw": 4.4}
    assert "Agile" in " ".join(
        _check(states={"control_enabled": "on"}, rolling_export=plan)
    )
    assert _check(states={"control_enabled": "off"}, rolling_export=plan) == []


def test_unknown_or_stale_physical_readings_fail_closed() -> None:
    assert "not initialised" in " ".join(
        guard.maintenance_energy_blockers(
            now=NOW,
            snapshot=None,
            happy_hour={},
            power_down={},
            foxess={},
            rolling_export={},
            states={},
        )
    )
    assert "not recent" in " ".join(
        _check(snapshot=_snapshot(timestamp=NOW - timedelta(minutes=4)))
    )
    assert "not verified" in " ".join(_check(snapshot=_snapshot(grid_export_kw=None)))


def test_install_and_restart_paths_each_recheck_energy_activity() -> None:
    code = UPDATE.read_text()
    assert "def _energy_maintenance_blockers(self)" in code
    assert "def _defer_for_energy_activity" in code
    assert 'pending["stage"] = "waiting_for_safe_energy_state"' in code
    assert 'pending["deferred_reason"] = reason' in code
    assert code.count("blockers = self._energy_maintenance_blockers()") >= 3
    install_check = code.index(
        'if not self.hass.services.has_service("update", "install")'
    )
    restart_check = code.index(
        'if not self.hass.services.has_service("homeassistant", "restart")'
    )
    assert (
        code.rfind("blockers = self._energy_maintenance_blockers()", 0, install_check)
        >= 0
    )
    assert (
        code.rfind("blockers = self._energy_maintenance_blockers()", 0, restart_check)
        >= 0
    )
