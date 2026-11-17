"""KEMS alpha9.221: source-verified Intelligent Octopus slot WhatsApp events."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
SOURCE = ROOT / "kems_core" / "whatsapp_message_plans.py"
spec = importlib.util.spec_from_file_location("alpha9220_intelligent_slot", SOURCE)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_actual_slot_start_uses_transition_not_next_slot_start():
    now = datetime(2026, 11, 17, 23, 31, tzinfo=UTC)
    changed = now - timedelta(minutes=1)
    key, msg = mod.intelligent_slot_message(
        state="on",
        changed_at=changed,
        now=now,
        end_time="2026-11-18T05:30:00+00:00",
    )
    assert key == "intelligent-slot:on:2026-11-17T23:30:00+00:00"
    assert "Cheap Slot Active" in msg
    assert "Start: 23:30" in msg
    assert "End: 05:30" in msg
    assert "EV and home-battery protections" in msg


def test_missing_or_earlier_end_is_tbc_not_invented():
    changed = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)
    now = changed + timedelta(minutes=1)
    for end in ("unknown", "unavailable", "2026-11-17T22:00:00Z", None):
        _, msg = mod.intelligent_slot_message(
            state="on", changed_at=changed, now=now, end_time=end
        )
        assert "Start: 23:30" in msg
        assert "End: TBC" in msg


def test_end_message_observed_time_and_dedupe_identity():
    changed = datetime(2026, 11, 18, 5, 30, tzinfo=UTC)
    key, msg = mod.intelligent_slot_message(
        state="off", changed_at=changed, now=changed
    )
    assert key == "intelligent-slot:off:2026-11-18T05:30:00+00:00"
    assert "Cheap Slot Ended" in msg
    assert "End: 05:30" in msg
    assert "KEMS continues" in msg
    assert (
        key
        != mod.intelligent_slot_message(
            state="off",
            changed_at=changed + timedelta(hours=1),
            now=changed + timedelta(hours=1),
        )[0]
    )


def test_not_an_event_when_unknown_or_stale_or_naive():
    at = datetime(2026, 11, 17, 20, tzinfo=UTC)
    for state in ("unknown", "unavailable", ""):
        assert mod.intelligent_slot_message(state=state, changed_at=at, now=at) is None
    assert (
        mod.intelligent_slot_message(
            state="on", changed_at=at, now=at + timedelta(minutes=6)
        )
        is None
    )
    assert (
        mod.intelligent_slot_message(
            state="on", changed_at=at.replace(tzinfo=None), now=at
        )
        is None
    )


def test_reporter_keeps_state_and_idempotency_without_affecting_control():
    source = (ROOT / "whatsapp_notifications.py").read_text()
    assert '"intelligent_slot_last_state": self._intelligent_slot_last_state' in source
    assert 'if value not in {"on", "off"}:' in source
    assert "changed_at < self._slot_setup_at" in source
    assert "await self._intelligent_slot_alerts(now)" in source
    assert "await self._send(key, message, private=False, now=now)" in source
    assert "legacy_intelligent_slot_mobile_automations" in source
    assert '"octopus intelligent slot notification on"' in source
    assert '"octopus intelligent slot end notification"' in source
    assert "No real slot has been started" in source
    assert "No real slot has ended" in source
    ast.parse(source)


def test_intelligent_slot_messages_have_real_line_breaks() -> None:
    on_time = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)
    off_time = on_time + timedelta(hours=6)
    _, on = mod.intelligent_slot_message(
        state="on",
        changed_at=on_time,
        now=on_time,
        end_time=off_time,
    )
    _, off = mod.intelligent_slot_message(
        state="off",
        changed_at=off_time,
        now=off_time,
    )
    assert "*\n🕒 Start: 23:30\n🕓 End: 05:30\n" in on
    assert "*\n🕒 End: 05:30\n" in off
    for message in (on, off):
        assert "\n" in message
        assert r"\n" not in message


def test_test_all_intelligent_examples_have_actual_line_breaks() -> None:
    tree = ast.parse((ROOT / "whatsapp_notifications.py").read_text())
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    on = next(value for value in strings if "Sample active-slot alert only." in value)
    off = next(value for value in strings if "Sample ended-slot alert only." in value)
    assert "*\n🕒 Start: 23:30\n🕓 End: TBC\n" in on
    assert "*\n🕒 End: 05:30\n" in off
    assert r"\n" not in on
    assert r"\n" not in off
