"""Alpha9.17 whole-integration Recorder and event-loop hygiene contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
HYGIENE = KEMS / "recorder_hygiene.py"
RECORDER_MAX_ATTRIBUTE_BYTES = 16_384

MANUAL_AGILE_OVERFLOW_ENTITIES = frozenset(
    {
        "sensor.kems_agile_smart_export_plan",
        "sensor.kems_agile_rolling_export_plan",
        "sensor.kems_agile_decision_audit",
        "sensor.kems_agile_slot_decisions_today",
        "sensor.kems_agile_shadow_status",
    }
)
ENTITY_OVERFLOW_ENTITIES = frozenset(
    {
        "sensor.kems_update_orchestrator_runtime",
        "sensor.kems_update_status",
        "sensor.kems_forecast_validation_status",
    }
)
LIVE_OVERFLOW_ENTITIES = MANUAL_AGILE_OVERFLOW_ENTITIES | ENTITY_OVERFLOW_ENTITIES


def _size(value: object) -> int:
    return len(
        json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode()
    )


def test_alpha917_covers_every_live_recorder_overflow_entity() -> None:
    """All eight entities proven oversized by the live HA log stay in scope."""
    assert {
        "sensor.kems_agile_smart_export_plan",
        "sensor.kems_agile_rolling_export_plan",
        "sensor.kems_agile_decision_audit",
        "sensor.kems_agile_slot_decisions_today",
        "sensor.kems_agile_shadow_status",
        "sensor.kems_update_orchestrator_runtime",
        "sensor.kems_update_status",
        "sensor.kems_forecast_validation_status",
    } == LIVE_OVERFLOW_ENTITIES
    assert len(MANUAL_AGILE_OVERFLOW_ENTITIES) == 5
    assert len(ENTITY_OVERFLOW_ENTITIES) == 3


def test_alpha917_manual_agile_publishers_carry_recorder_state_info() -> None:
    """One central manager boundary protects plan, rolling, audit and shadow states."""
    hygiene = HYGIENE.read_text(encoding="utf-8")
    assert "RECORDER_LIVE_ONLY_ATTRIBUTES = frozenset({MATCH_ALL})" in hygiene
    assert "state_info=RECORDER_LIVE_ONLY_STATE_INFO" in hygiene
    assert (
        "agile.EfficientAgileSmartExportManager._set = recorder_safe_agile_set"
        in hygiene
    )

    for source_name in (
        "agile_smart_export.py",
        "agile_rolling_replan_runtime.py",
        "agile_validation_evidence_runtime.py",
        "agile_shadow_command_runtime.py",
    ):
        assert "self._set(" in (KEMS / source_name).read_text(encoding="utf-8")


def test_alpha917_updater_and_forecast_entities_use_live_only_boundaries() -> None:
    """The remaining three overflow paths are covered without deleting live detail."""
    hygiene = HYGIENE.read_text(encoding="utf-8")
    updater = (KEMS / "update_orchestrator.py").read_text(encoding="utf-8")
    sensors = (KEMS / "sensor.py").read_text(encoding="utf-8")

    assert "sensor.kems_update_orchestrator_runtime" in hygiene
    assert "sensor.kems_update_orchestrator_runtime" in updater
    assert 'super().__init__(coordinator, "update_status")' in updater
    assert 'key="forecast_validation_status"' in sensors
    assert "class RecorderSafeUpdateStatusSensor" in hygiene
    assert "class RecorderSafeForecastValidationSensor" in hygiene
    assert "_unrecorded_attributes = RECORDER_LIVE_ONLY_ATTRIBUTES" in hygiene


def test_alpha917_match_all_keeps_large_live_payload_but_recorder_compact() -> None:
    """MATCH_ALL semantics preserve live payload while Recorder keeps only metadata."""
    rich = {
        "friendly_name": "KEMS live evidence",
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "measurement",
        "today_slots": [{"detail": "x" * 800} for _ in range(48)],
        "decision_trace": [{"detail": "y" * 600} for _ in range(60)],
        "history": [{"detail": "z" * 500} for _ in range(40)],
    }
    assert _size(rich) > RECORDER_MAX_ATTRIBUTE_BYTES

    # Home Assistant MATCH_ALL retains these standard metadata keys while dropping
    # integration-specific live attributes from Recorder. The state machine still
    # receives the original rich mapping unchanged.
    recorded = {
        key: rich[key]
        for key in (
            "friendly_name",
            "unit_of_measurement",
            "device_class",
            "state_class",
        )
    }
    assert _size(recorded) < RECORDER_MAX_ATTRIBUTE_BYTES
    assert len(rich["today_slots"]) == 48
    assert len(rich["decision_trace"]) == 60


def test_alpha917_installs_before_first_coordinator_publication() -> None:
    """Startup publications must be Recorder-safe, not only later refreshes."""
    source = (KEMS / "__init__.py").read_text(encoding="utf-8")
    hygiene = HYGIENE.read_text(encoding="utf-8")
    install_at = source.index("install_alpha916_recorder_hygiene()")
    first_refresh_at = source.index(
        "await coordinator.async_config_entry_first_refresh()"
    )
    assert install_at < first_refresh_at
    assert "def install_alpha916_recorder_hygiene()" in hygiene
    assert "install_alpha917_recorder_hygiene()" in hygiene


def test_alpha917_updater_file_reads_are_executor_cached() -> None:
    """Version/dashboard verification must not synchronously read files on HA's loop."""
    hygiene = HYGIENE.read_text(encoding="utf-8")
    assert "async_add_executor_job(\n            raw_disk_version_reader" in hygiene
    assert "def cached_files_version()" in hygiene
    assert "def cached_dashboard_current(self)" in hygiene
    assert "orchestrator_class._dashboard_current = cached_dashboard_current" in hygiene


def test_alpha917_remains_presentation_and_runtime_hygiene_only() -> None:
    """The repair cannot change optimiser decisions or cross the FoxESS write gate."""
    hygiene = HYGIENE.read_text(encoding="utf-8")
    assert "providers.foxess" not in hygiene
    assert "forecast_path_scheduler" not in hygiene
    assert "system_profile" not in hygiene
    assert "commands_permitted = True" not in hygiene
    assert "safe_to_write_hardware = True" not in hygiene
    assert "update.install" not in hygiene
