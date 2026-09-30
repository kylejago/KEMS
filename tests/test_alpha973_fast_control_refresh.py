"""Alpha9.73 fast EV / Intelligent control refresh regressions."""

from __future__ import annotations

import json
from pathlib import Path

from kems_core import (
    critical_control_refresh_entity_ids,
    meaningful_control_state_transition,
)

ROOT = Path(__file__).resolve().parents[1]


def test_fast_refresh_watches_only_discrete_control_authority_sources() -> None:
    watched = critical_control_refresh_entity_ids(
        "sensor.ohme_status",
        "binary_sensor.ev_connected",
        "binary_sensor.ev_connected",
        "binary_sensor.intelligent_slot",
        "binary_sensor.off_peak",
        None,
    )

    assert watched == (
        "sensor.ohme_status",
        "binary_sensor.ev_connected",
        "binary_sensor.intelligent_slot",
        "binary_sensor.off_peak",
    )
    assert "sensor.ohme_power" not in watched


def test_only_meaningful_discrete_transitions_request_fast_refresh() -> None:
    assert meaningful_control_state_transition("off", "on") is True
    assert meaningful_control_state_transition("Plugged in", "Charging") is True
    assert meaningful_control_state_transition("on", "on") is False
    assert meaningful_control_state_transition(None, "on") is False
    assert meaningful_control_state_transition("off", None) is False


def test_alpha973_release_identity_and_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/kems/manifest.json").read_text(encoding="utf-8")
    )
    bundle = json.loads(
        (ROOT / "release/kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.73"
    assert reason.startswith(
        "Alpha9.73 removes the normal coordinator-poll delay from EV battery protection"
    )
    assert "request an immediate KEMS refresh" in reason
    assert "does not pre-authorise an Intelligent extra slot" in reason
    assert "Alpha9.72 tariff confirmation" in reason
