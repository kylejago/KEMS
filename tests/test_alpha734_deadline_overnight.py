"""Regression guards for Alpha7.34 deadline prevention and cheap-window safety."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from kems_core import Snapshot

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha734_deadline_guard.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
TARIFF = KEMS / "tariff.py"
MANIFEST = KEMS / "manifest.json"
BACKEND_DOC = ROOT / "docs" / "hardware-backend-contract.md"
LONDON = ZoneInfo("Europe/London")


def test_alpha734_release_identity_is_retained_in_alpha8() -> None:
    """The deadline guard remains part of the Alpha8 parity baseline."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert PATCH.exists()


def test_alpha734_patch_parses_and_installs_after_alpha731() -> None:
    """Alpha7.31 stays the proven base; Alpha7.34 is the outer policy patch."""
    ast.parse(PATCH.read_text(encoding="utf-8"))
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha734_deadline_guard_patch" in loader
    assert loader.rindex("install_alpha734_deadline_guard_patch()") > loader.rindex(
        "install_alpha731_solar_headroom_patch()"
    )


def test_alpha734_calculates_latest_safe_start_from_solar_aware_capacity() -> None:
    """The new guard must work backwards from physical shared-AC capacity."""
    source = PATCH.read_text(encoding="utf-8")
    for token in (
        "DEADLINE_GUARD_MINUTES = 10",
        "CAPACITY_STEP_MINUTES = 5",
        "_capacity_segments",
        "_latest_safe_start",
        "solar_aware_remaining_capacity_kwh",
        "solar_aware_deadline_margin_kwh",
        "latest_safe_export_start",
        "guarded_latest_safe_export_start",
        "target_physically_reachable_now",
        "skippable_half_hours",
        "KEMS hourly solar forecast",
    ):
        assert token in source


def test_alpha734_guard_escalates_without_bypassing_solar_headroom() -> None:
    """Deadline pressure must still pass through Alpha7.31 inverter headroom."""
    source = PATCH.read_text(encoding="utf-8")
    assert "original_dispatch = dispatch" in source
    assert 'evidence.get("battery_inverter_headroom_kw")' in source
    assert '"deadline_guard_applied": True' in source
    assert '"mode": guard_mode' in source
    assert "full safe discharge protects the" in source
    assert "safe_to_write_hardware = True" not in source
    assert ".services.async_call(" not in source


def test_tonights_29_percent_example_would_enter_guard_before_2200() -> None:
    """A 29% SOC should not be left until 22:44 with a 7 kW 23:30 deadline."""
    battery_capacity_kwh = 56.42
    current_soc = 29.0
    target_soc = 10.0
    discharge_efficiency = 0.95
    maximum_discharge_kw = 7.0

    required_ac_kwh = (
        battery_capacity_kwh * (current_soc - target_soc) / 100
    ) * discharge_efficiency
    deadline = datetime(2026, 8, 19, 23, 30, tzinfo=LONDON)
    latest_safe = deadline - timedelta(hours=required_ac_kwh / maximum_discharge_kw)
    guarded_start = latest_safe - timedelta(minutes=10)

    assert required_ac_kwh > 10.0
    assert latest_safe.hour == 22
    assert latest_safe.minute < 5
    assert guarded_start < datetime(2026, 8, 19, 22, 0, tzinfo=LONDON)


def test_alpha734_legacy_extra_slot_block_is_superseded_safely() -> None:
    """Alpha8.58 may restore extras only behind a fail-closed evidence gate."""
    source = TARIFF.read_text(encoding="utf-8")
    assert "_intelligent_extra_slot_evidence" in source
    assert "large_import_permitted" in source
    assert "automatic_intelligent_extra" in source
    assert "INTELLIGENT_EV_MIN_POWER_KW" in source
    assert "settings.intelligent_slots_enabled" in source


def test_retained_intelligent_observation_is_not_rewritten_by_history() -> None:
    """Historical raw flags remain data; only live tariff resolution grants import."""
    old_extra_slot = Snapshot(
        off_peak=False,
        intelligent_slot=False,
        ev_charging=True,
    )
    overnight = Snapshot(
        off_peak=True,
        intelligent_slot=False,
        ev_charging=False,
    )

    assert old_extra_slot.cheap_period_confirmed is False
    assert overnight.cheap_period_confirmed is True


def test_vendor_neutral_backend_contract_is_recorded_before_alpha_ess() -> None:
    """Future inverter support must plug into KEMS rather than fork its planner."""
    source = BACKEND_DOC.read_text(encoding="utf-8")
    assert "FoxESS" in source
    assert "Alpha ESS" in source
    assert "ControlState" in source
    assert "vendor-neutral" in source
    assert (
        "Do not implement Alpha ESS writes before FoxESS live control is proven"
        in source
    )
