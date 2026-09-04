"""Regression coverage for Alpha8.32 Tomorrow SOC continuity."""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from kems_core.tomorrow_soc_handoff import project_tomorrow_midnight_soc

ROOT = Path(__file__).parents[1]
LONDON = ZoneInfo("Europe/London")


def test_uploaded_alpha831_case_starts_tomorrow_from_precheap_projection() -> None:
    """42.9% viewed SOC must not seed Tomorrow when 10% is projected at 23:30."""
    midnight_soc, evidence = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 26, 21, 1, tzinfo=LONDON),
        current_soc_percent=42.9,
        projected_precheap_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )

    assert midnight_soc == 15.893
    assert evidence["starting_soc_percent"] == 10.0
    assert evidence["stored_charge_kwh_before_midnight"] == 3.325
    assert evidence["charge_hours_before_midnight"] == 0.5
    assert evidence["basis"] == "forecast projected SOC at cheap start"
    assert evidence["hardware_writes"] == "blocked"


def test_first_tomorrow_half_hour_can_only_reach_about_21_8_percent() -> None:
    """Lock the diagnostic discontinuity: 00:00 cannot end at 48.8% from 10%."""
    midnight_soc, _ = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 26, 21, 1, tzinfo=LONDON),
        current_soc_percent=42.9,
        projected_precheap_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )
    stored_next_half_hour = 7.0 * 0.5 * 0.95
    ending_soc = midnight_soc + stored_next_half_hour / 56.42 * 100.0

    assert round(ending_soc, 3) == 21.786
    assert round(ending_soc, 1) == 21.8
    assert round(ending_soc, 1) != 48.8


def test_active_cheap_window_uses_current_soc_without_replaying_elapsed_charge() -> (
    None
):
    midnight_soc, evidence = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 26, 23, 45, tzinfo=LONDON),
        current_soc_percent=18.0,
        projected_precheap_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )

    assert evidence["basis"] == "current SOC inside active cheap window"
    assert evidence["starting_soc_percent"] == 18.0
    assert evidence["charge_hours_before_midnight"] == 0.25
    assert evidence["stored_charge_kwh_before_midnight"] == 1.662
    assert midnight_soc == 20.947


def test_non_wrapping_cheap_window_does_not_invent_pre_midnight_charge() -> None:
    midnight_soc, evidence = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 26, 21, 1, tzinfo=LONDON),
        current_soc_percent=42.9,
        projected_precheap_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(0, 0),
        offpeak_end=time(6, 0),
    )

    assert midnight_soc == 42.9
    assert evidence["active"] is False
    assert evidence["basis"] == "no pre-midnight cheap window"


def test_runtime_rebuilds_and_republishes_tomorrow_from_midnight_handoff() -> None:
    runtime = (
        ROOT / "custom_components/kems/agile_smart_export_runtime.py"
    ).read_text()
    handoff = (
        ROOT / "custom_components/kems/agile_tomorrow_soc_handoff.py"
    ).read_text()
    successor = (
        ROOT / "custom_components/kems/agile_current_day_settlement.py"
    ).read_text()
    rollover = (ROOT / "custom_components/kems/agile_midnight_rollover.py").read_text()
    flow = (ROOT / "custom_components/kems/agile_flow_presentation.py").read_text()
    canonical = (
        ROOT / "custom_components/kems/agile_canonical_flow_accounting.py"
    ).read_text()
    live = (
        ROOT / "custom_components/kems/agile_live_solar_soc_continuity.py"
    ).read_text()

    # Alpha8.32's Tomorrow handoff may remain the direct runtime manager or be
    # inherited by later canonical managers. Either way the handoff must stay
    # in the active runtime chain rather than being bypassed.
    direct_handoff = (
        "EfficientAgileSmartExportManager = TomorrowSocHandoffAgileSmartExportManager"
        in runtime
    )
    settlement_successor_handoff = (
        "EfficientAgileSmartExportManager = SettledCurrentDayAgileSmartExportManager"
        in runtime
        and "TomorrowSocHandoffAgileSmartExportManager" in successor
        and "class SettledCurrentDayAgileSmartExportManager" in successor
    )
    rollover_successor_handoff = (
        "EfficientAgileSmartExportManager = MidnightRolloverAgileSmartExportManager"
        in runtime
        and "SettledCurrentDayAgileSmartExportManager" in rollover
        and "class MidnightRolloverAgileSmartExportManager" in rollover
        and "TomorrowSocHandoffAgileSmartExportManager" in successor
        and "class SettledCurrentDayAgileSmartExportManager" in successor
    )
    flow_successor_handoff = (
        "EfficientAgileSmartExportManager = FlowPresentationAgileSmartExportManager"
        in runtime
        and "MidnightRolloverAgileSmartExportManager" in flow
        and "class FlowPresentationAgileSmartExportManager" in flow
        and "SettledCurrentDayAgileSmartExportManager" in rollover
        and "TomorrowSocHandoffAgileSmartExportManager" in successor
    )
    canonical_owner = (
        "EfficientAgileSmartExportManager = "
        "CanonicalFlowAccountingAgileSmartExportManager"
    )
    canonical_successor_handoff = (
        canonical_owner in runtime
        and "FlowPresentationAgileSmartExportManager" in canonical
        and "class CanonicalFlowAccountingAgileSmartExportManager" in canonical
        and "MidnightRolloverAgileSmartExportManager" in flow
        and "SettledCurrentDayAgileSmartExportManager" in rollover
        and "TomorrowSocHandoffAgileSmartExportManager" in successor
    )
    live_owner = (
        "EfficientAgileSmartExportManager = "
        "LiveSolarSocContinuityAgileSmartExportManager"
    )
    live_successor_handoff = (
        live_owner in runtime
        and "CanonicalFlowAccountingAgileSmartExportManager" in live
        and "class LiveSolarSocContinuityAgileSmartExportManager" in live
        and "FlowPresentationAgileSmartExportManager" in canonical
        and "MidnightRolloverAgileSmartExportManager" in flow
        and "SettledCurrentDayAgileSmartExportManager" in rollover
        and "TomorrowSocHandoffAgileSmartExportManager" in successor
    )
    assert (
        direct_handoff
        or settlement_successor_handoff
        or rollover_successor_handoff
        or flow_successor_handoff
        or canonical_successor_handoff
        or live_successor_handoff
    )
    assert "project_tomorrow_midnight_soc(" in handoff
    assert "self._compare_day(" in handoff
    assert 'state["tomorrow_slots"] = tomorrow_slots' in handoff
    assert "self._publish(self._state)" in handoff
    assert '"hardware_writes": "blocked"' in handoff
    assert ".services.async_call(" not in handoff
    assert "safe_to_write_hardware = True" not in handoff


def test_alpha832_release_contract_remains_successor_safe() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert (
        str(version).startswith("0.9.0-alpha9") or int(version.rsplit(".", 1)[1]) >= 32
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
