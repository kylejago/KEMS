"""Regression coverage for the Alpha8.19 clean managed-dashboard rebuild."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"
SLOTS = ROOT / "custom_components" / "kems" / "agile_slots_state.py"
INIT = ROOT / "custom_components" / "kems" / "__init__.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"

EXPECTED_PATHS = [
    "home",
    "live-data",
    "kems",
    "compare",
    "tomorrow",
    "history",
    "system",
]

STALE_PRESENTATION_ENTITIES = (
    "sensor.kems_agile_smart_export_plan",
    "sensor.kems_agile_live_scenario",
    "sensor.kems_agile_export_rate_now",
    "sensor.kems_agile_price_data_quality",
    "sensor.kems_compare_kems_no_export_cost_today",
    "sensor.kems_compare_full_kems_forecast_cost_today",
)


def _content() -> str:
    return PACKAGED.read_text(encoding="utf-8")


def test_dashboard_is_fresh_seven_view_customer_product() -> None:
    content = _content()
    parsed = yaml.safe_load(content)

    assert parsed["title"] == "KEMS"
    assert [view["path"] for view in parsed["views"]] == EXPECTED_PATHS
    assert [view["title"] for view in parsed["views"]][:4] == [
        "Home",
        "Live Data",
        "KEMS",
        "Compare",
    ]
    assert "Battery & Solar" not in content
    assert "Full KEMS Agile" not in content
    assert "Compare every KEMS type" not in content


def test_dashboard_uses_verified_stable_entities_not_retired_presentation_states() -> (
    None
):
    content = _content()

    for entity_id in STALE_PRESENTATION_ENTITIES:
        assert entity_id not in content

    for entity_id in (
        "sensor.kems_status",
        "sensor.kems_house_load",
        "sensor.kems_current_import_rate",
        "sensor.kems_observed_cost_today",
        "sensor.kems_simulated_kems_cost_today",
        "sensor.kems_simulated_house_load_power",
        "sensor.kems_simulated_battery_state_of_charge",
        "sensor.kems_forecast_solar_tomorrow",
        "sensor.kems_update_status",
        "sensor.kems_agile_slots",
        "sensor.kems_energy_cost_comparison",
    ):
        assert entity_id in content


def test_optional_uncommissioned_live_hardware_is_rendered_defensively() -> None:
    content = _content()

    assert "['unknown', 'unavailable', 'none', '']" in content
    assert "Optional physical sensors remain `—` until commissioned" in content
    assert (
        "Live solar/battery values remain `—` until the physical system is commissioned"
        in content
    )


def test_agile_slots_has_one_stable_state_backed_by_retained_runtime_data() -> None:
    content = _content()
    slots = SLOTS.read_text(encoding="utf-8")
    init = INIT.read_text(encoding="utf-8")

    assert "sensor.kems_agile_slots" in content
    assert 'ENTITY_ID = "sensor.kems_agile_slots"' in slots
    assert 'getattr(coordinator, "agile_smart_export_state", None)' in slots
    assert 'state.get("today_slots")' in slots
    assert 'state.get("tomorrow_slots")' in slots
    assert "coordinator.async_add_listener(publish)" in slots
    assert "async_setup_agile_slots_state(hass, entry, coordinator)" in init


def test_sync_and_verification_use_exact_same_fresh_packaged_bytes() -> None:
    pipeline = PIPELINE.read_text(encoding="utf-8")

    assert SOURCE.read_bytes() == PACKAGED.read_bytes()
    assert "PACKAGED_DASHBOARD_PATH.read_bytes()" in pipeline
    assert (
        "dashboard._combined_master_dashboard_bytes = _fresh_dashboard_bytes"
        in pipeline
    )
    assert "convergent._managed_dashboard_bytes = _fresh_dashboard_bytes" in pipeline
    assert "original_builder" not in pipeline


def test_alpha819_release_scope_keeps_external_versions_and_hardware_lock() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    slots = SLOTS.read_text(encoding="utf-8")

    assert manifest["version"].startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert (
        str(manifest["version"]).startswith("0.9.0-alpha9")
        or int(manifest["version"].rsplit(".", 1)[-1]) >= 19
    )
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert str(bundle["components"]["property_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["pi_agent"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["public_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-public.")
    )
    assert '"hardware_writes": "blocked"' in slots
