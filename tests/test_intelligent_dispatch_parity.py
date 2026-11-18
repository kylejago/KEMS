"""Regression tests for read-only Octopus Intelligent / Ohme parity."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from kems_core.intelligent_dispatch_parity import (
    compare_intelligent_and_ohme,
    fixed_overnight_offpeak,
)

LONDON = ZoneInfo("Europe/London")


def _sample(hour: int, minute: int = 0, **updates):
    values = {
        "now": datetime(2026, 11, 19, hour, minute, tzinfo=LONDON),
        "legacy_slot": False,
        "legacy_planned_dispatch": False,
        "ohme_charge_mode": "Smart charge",
        "ohme_power_kw": 0.0,
        "ohme_charging": False,
        "ohme_plan_active": False,
    }
    values.update(updates)
    return compare_intelligent_and_ohme(**values)


def test_overnight_window_is_excluded_from_daytime_parity() -> None:
    assert fixed_overnight_offpeak(
        datetime(2026, 11, 19, 23, 30, tzinfo=LONDON)
    )
    assert fixed_overnight_offpeak(
        datetime(2026, 11, 19, 5, 29, tzinfo=LONDON)
    )
    assert not fixed_overnight_offpeak(
        datetime(2026, 11, 19, 5, 30, tzinfo=LONDON)
    )
    assert not fixed_overnight_offpeak(
        datetime(2026, 11, 19, 23, 29, tzinfo=LONDON)
    )
    result = _sample(23, 45, legacy_slot=True)
    assert result["classification"] == "overnight_excluded"


def test_smart_dispatch_matches_real_smart_charging() -> None:
    result = _sample(
        14,
        legacy_slot=True,
        legacy_planned_dispatch=True,
        ohme_power_kw=7.0,
        ohme_charging=True,
        ohme_plan_active=True,
    )
    assert result["classification"] == "both_active"
    assert result["ohme_smart_charging_now"] is True
    assert result["supplier_discount_confirmed"] is False


def test_planned_dispatch_can_be_on_while_ev_is_paused() -> None:
    result = _sample(
        14, legacy_slot=True, legacy_planned_dispatch=True, ohme_power_kw=0.0
    )
    assert result["classification"] == "legacy_only"


def test_ohme_smart_charging_can_be_active_without_octopus_dispatch() -> None:
    result = _sample(14, ohme_power_kw=7.2, ohme_charging=True)
    assert result["classification"] == "ohme_only"
    assert result["controls_tariff_or_battery"] is False


def test_manual_boost_charging_is_not_a_smart_charge_dispatch() -> None:
    result = _sample(
        14, ohme_charge_mode="Max charge", ohme_power_kw=7.2, ohme_charging=True
    )
    assert result["classification"] == "both_inactive"
    assert result["ohme_measured_charging"] is True
    assert result["ohme_smart_charging_now"] is False


def test_absent_mode_or_power_cannot_count_as_a_match() -> None:
    assert (
        _sample(14, ohme_charge_mode=None, ohme_power_kw=7.0)[
            "classification"
        ]
        == "evidence_incomplete"
    )
    assert (
        _sample(14, ohme_power_kw=None)["classification"]
        == "evidence_incomplete"
    )
    assert (
        _sample(14, legacy_planned_dispatch=None)["classification"]
        == "evidence_incomplete"
    )


def test_ohme_charge_plan_is_not_a_discount_authority() -> None:
    result = _sample(14, ohme_plan_active=True)
    assert result["classification"] == "both_inactive"
    assert result["supplier_discount_confirmed"] is False
    assert result["ohme_planned_slot_active"] is True


def test_comparison_is_not_wired_into_control() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    source = (root / "legacy_intelligent_parity_monitor.py").read_text(
        encoding="utf-8"
    )
    assert "services.async_call(" not in source
    assert "async_apply_pending(" not in source
    assert "ControlEngine.plan" not in source
    assert "resolve_tariff(" not in source
    assert "set_state(" not in source
