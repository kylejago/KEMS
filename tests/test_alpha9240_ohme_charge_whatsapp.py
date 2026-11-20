"""Observed Ohme charging WhatsApp messages, independent of Octopus tariffs."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
TEMPLATES = ROOT / "kems_core" / "whatsapp_message_plans.py"
REPORTER = ROOT / "whatsapp_notifications.py"
spec = importlib.util.spec_from_file_location("kems_ohme_charge_messages", TEMPLATES)
assert spec is not None and spec.loader is not None
messages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(messages)


def test_ohme_messages_are_observations_not_discounted_tariff_claims() -> None:
    observed = datetime(2026, 11, 21, 6, 40, tzinfo=UTC)
    on = messages.ohme_charging_message(
        state="on", observed_at=observed, now=observed
    )
    off = messages.ohme_charging_message(
        state="off", observed_at=observed + timedelta(minutes=30),
        now=observed + timedelta(minutes=30),
    )
    assert on is not None and off is not None
    assert on[0] == "ohme-charge:on:2026-11-21T06:40:00+00:00"
    assert off[0] == "ohme-charge:off:2026-11-21T07:10:00+00:00"
    assert "EV Charging Started" in on[1]
    assert "EV Charging Stopped" in off[1]
    assert "Observed: 06:40" in on[1]
    assert "does not confirm an Octopus discounted slot" in on[1]
    assert "not evidence" in off[1]
    assert "\n" in on[1]
    assert r"\n" not in on[1]
    assert r"\n" not in off[1]


def test_unknown_or_stale_event_does_not_produce_a_message() -> None:
    observed = datetime(2026, 11, 21, 6, 40, tzinfo=UTC)
    for state in ("unknown", "unavailable", "", "paused"):
        assert messages.ohme_charging_message(
            state=state, observed_at=observed, now=observed
        ) is None
    assert messages.ohme_charging_message(
        state="on", observed_at=observed,
        now=observed + timedelta(minutes=6),
    ) is None
    assert messages.ohme_charging_message(
        state="on", observed_at=observed.replace(tzinfo=None), now=observed
    ) is None


def test_reporter_is_power_gated_bounded_and_never_gives_tariff_authority() -> None:
    source = REPORTER.read_text(encoding="utf-8")
    assert "await self._observed_ohme_charge_alerts(now)" in source
    assert "not 0 <= age <= 180" in source
    assert "connected is True and charge is True and power >= 0.25 and age <= 90" in source
    assert 'elif charge is False and power <= 0.1:' in source
    assert "self._ohme_charging_last_state is None" in source
    assert "self._ohme_charge_off_since" in source
    assert "timedelta(minutes=2)" in source
    assert '"intelligent_slot_alerts_enabled": False' in source
    assert "await self._send(key, message, private=False, now=now)" in source
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_observed_ohme_charge_alerts"
    )
    assert "Force Charge" not in (ast.get_source_segment(source, method) or "")
