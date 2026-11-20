"""Alpha9.224 regressions for overnight cheap tariff / WhatsApp independence."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
GATE = ROOT / "kems_core" / "tariff_commissioning_gate.py"
PLANS = ROOT / "kems_core" / "whatsapp_message_plans.py"
REPORTER = ROOT / "whatsapp_notifications.py"
COMMISSIONING = ROOT / "commissioning.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("alpha9224_tariff_gate", GATE)
messages = _load("alpha9224_messages", PLANS)


def _snapshot(
    *,
    off_peak=False,
    intel=False,
    ev=False,
    stale=("intelligent_slot",),
    rate=6.6,
    cheap=False,
):
    return SimpleNamespace(
        current_import_rate=rate,
        tariff_stale_fields=stale,
        off_peak=off_peak,
        intelligent_slot=intel,
        ev_charging=ev,
        cheap_period_confirmed=cheap,
    )


def test_optional_intelligent_outage_cannot_disable_scheduled_overnight_cheap():
    assert gate.tariff_data_commissioning_ready(
        _snapshot(off_peak=True, stale=("intelligent_slot",), rate=6.6, cheap=True)
    )
    assert gate.tariff_data_commissioning_ready(
        _snapshot(off_peak=False, stale=("intelligent_slot",), rate=35.88)
    )


def test_real_tariff_and_extra_slot_uncertainty_still_fail_closed():
    scenarios = (
        _snapshot(off_peak=True, stale=("intelligent_slot", "off_peak")),
        _snapshot(off_peak=True, stale=("current_import_rate", "intelligent_slot")),
        _snapshot(off_peak=True, rate=None),
        _snapshot(ev=True),  # Extra EV charged without a confirmed Intelligent slot.
        _snapshot(off_peak=None),
        _snapshot(intel=True),
        _snapshot(stale=("off_peak",)),
    )
    for snapshot in scenarios:
        assert not gate.tariff_data_commissioning_ready(snapshot)


def test_real_extra_slot_remains_eligible_only_with_fresh_tariff_data():
    assert gate.tariff_data_commissioning_ready(
        _snapshot(intel=True, ev=True, stale=(), cheap=True)
    )


def test_normal_offpeak_messages_use_source_transition_not_forecast():
    start = datetime(2026, 11, 18, 23, 30, tzinfo=UTC)
    end = start + timedelta(hours=6)
    start_key, on = messages.regular_offpeak_message(
        state="on", changed_at=start, now=start + timedelta(seconds=60)
    )
    end_key, off = messages.regular_offpeak_message(
        state="off", changed_at=end, now=end + timedelta(seconds=40)
    )
    assert start_key.startswith("regular-offpeak:on:")
    assert end_key.startswith("regular-offpeak:off:")
    assert "Off-Peak Active" in on and "23:30" in on
    assert "Off-Peak Ended" in off and "05:30" in off
    assert "\\n" not in on + off
    assert "\n" in on + off


def test_no_stale_or_fabricated_offpeak_boundaries():
    now = datetime(2026, 11, 18, 5, 30, tzinfo=UTC)
    for state in ("unavailable", "unknown", ""):
        assert (
            messages.regular_offpeak_message(state=state, changed_at=now, now=now)
            is None
        )
    assert (
        messages.regular_offpeak_message(
            state="off", changed_at=now - timedelta(minutes=7), now=now
        )
        is None
    )
    assert (
        messages.regular_offpeak_message(
            state="on", changed_at=now.replace(tzinfo=None), now=now
        )
        is None
    )


def test_reporter_persists_independent_offpeak_dedupe_and_no_extra_control():
    source = REPORTER.read_text(encoding="utf-8")
    assert '"regular_offpeak_last_state": self._regular_offpeak_last_state' in source
    assert "await self._regular_offpeak_alerts(now)" in source
    assert "await self._observed_ohme_charge_alerts(now)" in source
    assert "regular_offpeak_transitions_accepted" in source
    assert "ohme_charging_transitions_accepted" in source
    assert "tariff_commissioning_blocked" in source
    assert 'not getattr(control, "commissioned", False)' in source
    assert '"intelligent_slot_alerts_enabled": False' in source
    ast.parse(source)
    commission = COMMISSIONING.read_text(encoding="utf-8")
    assert "tariff_data_commissioning_ready(data.snapshot)" in commission
    assert "and not data.snapshot.tariff_stale_fields" not in commission
