"""Alpha9.73 fast EV / Intelligent control refresh regressions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from custom_components.kems.coordinator import (
    KEMSCoordinator,
    _critical_control_refresh_entities,
)
from custom_components.kems.providers.entity_map import KEMSEntities

ROOT = Path(__file__).resolve().parents[1]


def test_fast_refresh_watches_only_discrete_control_authority_sources() -> None:
    entities = KEMSEntities(
        ev_status="sensor.ohme_status",
        ev_connected="binary_sensor.ev_connected",
        ev_charging="binary_sensor.ev_connected",
        ev_power_kw="sensor.ohme_power",
        intelligent_slot="binary_sensor.intelligent_slot",
        off_peak="binary_sensor.off_peak",
    )

    watched = _critical_control_refresh_entities(entities)

    assert watched == (
        "sensor.ohme_status",
        "binary_sensor.ev_connected",
        "binary_sensor.intelligent_slot",
        "binary_sensor.off_peak",
    )
    assert "sensor.ohme_power" not in watched


def test_meaningful_state_transition_requests_prompt_refresh() -> None:
    class FakeCoordinator:
        def __init__(self) -> None:
            self.refresh_count = 0
            self._last_critical_refresh_event = None
            self.hass = SimpleNamespace(async_create_task=asyncio.create_task)

        async def async_request_refresh(self) -> None:
            self.refresh_count += 1

    async def exercise() -> FakeCoordinator:
        coordinator = FakeCoordinator()
        changed = SimpleNamespace(
            data={
                "entity_id": "binary_sensor.intelligent_slot",
                "old_state": SimpleNamespace(state="off"),
                "new_state": SimpleNamespace(
                    state="on",
                    entity_id="binary_sensor.intelligent_slot",
                ),
            }
        )
        KEMSCoordinator._handle_critical_control_source_change(coordinator, changed)
        await asyncio.sleep(0)

        unchanged = SimpleNamespace(
            data={
                "entity_id": "binary_sensor.intelligent_slot",
                "old_state": SimpleNamespace(state="on"),
                "new_state": SimpleNamespace(
                    state="on",
                    entity_id="binary_sensor.intelligent_slot",
                ),
            }
        )
        KEMSCoordinator._handle_critical_control_source_change(coordinator, unchanged)
        await asyncio.sleep(0)
        return coordinator

    coordinator = asyncio.run(exercise())

    assert coordinator.refresh_count == 1
    assert coordinator._last_critical_refresh_event is not None
    assert (
        coordinator._last_critical_refresh_event["entity_id"]
        == "binary_sensor.intelligent_slot"
    )
    assert coordinator._last_critical_refresh_event["old_state"] == "off"
    assert coordinator._last_critical_refresh_event["new_state"] == "on"


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
