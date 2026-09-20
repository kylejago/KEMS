"""Alpha9.61 Intelligent extra-slot demand-corroboration regressions."""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from tariff import TariffSettings, resolve_tariff

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
LONDON = ZoneInfo("Europe/London")

AUTOMATIC = TariffSettings(
    mode="automatic",
    day_rate_pence=28.3036,
    offpeak_rate_pence=3.4933,
    standing_charge_pence=53.70435,
    offpeak_start=time(23, 30),
    offpeak_end=time(5, 30),
    intelligent_slots_enabled=True,
)


def test_intelligent_extra_slot_is_not_vetoed_by_battery_supported_ev_load() -> None:
    """Low grid demand cannot disprove a slot while the battery is feeding the EV."""
    now = datetime(2026, 9, 19, 10, 48, 25, tzinfo=LONDON)
    result = resolve_tariff(
        settings=AUTOMATIC,
        now=now,
        live_current_import_rate=28.3036,
        live_next_import_rate=3.4933,
        live_current_export_rate=0.0,
        live_standing_charge=53.70435,
        live_off_peak=False,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 9, 19, 10, 47, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 9, 19, 11, 0, 0, tzinfo=LONDON),
        ev_connected=True,
        ev_charging=True,
        ev_power_kw=7.387,
        ev_soc=80.0,
        live_current_demand_kw=1.475,
        fallback_export_rate=0.0,
    )

    assert result.source == "automatic_intelligent_extra"
    assert result.intelligent_slot is True
    assert result.off_peak is False
    assert result.current_import_rate == 3.4933
    assert result.intelligent_slot_confirmation == "confirmed"
    evidence = result.intelligent_slot_evidence
    assert evidence["confirmed"] is True
    assert evidence["octopus_intelligent_slot"] is True
    assert evidence["octopus_intelligent_window_active"] is True
    assert evidence["ohme_charging"] is True
    assert evidence["ohme_power_active"] is True
    assert evidence["octopus_price_corroborated"] is True
    assert evidence["octopus_demand_corroborated"] is False
    assert evidence["octopus_demand_corroboration_required"] is False
    assert evidence["large_import_permitted"] is True


def test_intelligent_extra_slot_still_fails_closed_without_active_ohme_charge() -> None:
    """Removing the demand veto must not remove the independent Ohme gate."""
    now = datetime(2026, 9, 19, 10, 48, 25, tzinfo=LONDON)
    result = resolve_tariff(
        settings=AUTOMATIC,
        now=now,
        live_current_import_rate=28.3036,
        live_next_import_rate=3.4933,
        live_current_export_rate=0.0,
        live_standing_charge=53.70435,
        live_off_peak=False,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 9, 19, 10, 47, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 9, 19, 11, 0, 0, tzinfo=LONDON),
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_soc=80.0,
        live_current_demand_kw=0.2,
        fallback_export_rate=0.0,
    )

    assert result.intelligent_slot is False
    assert result.intelligent_slot_confirmation == (
        "Ohme does not confirm active charging"
    )
    assert result.intelligent_slot_evidence["confirmed"] is False
    assert result.intelligent_slot_evidence["large_import_permitted"] is False


def test_alpha961_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.68"
    assert reason.startswith("Alpha9.67")
    assert "Alpha9.62 promotes the optional Grid import prevention bias" in reason
    assert "Alpha9.61 fixes Intelligent extra-slot confirmation" in reason
    assert "Grid-demand corroboration" in reason
    assert "diagnostic evidence" in reason
    assert "no longer an authority gate" in reason
    assert "Price, slot-window and Ohme evidence remain fail-closed" in reason
    assert "bounded FoxESS write scope is unchanged" in reason
