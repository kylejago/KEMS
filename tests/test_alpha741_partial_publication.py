"""Regression coverage for Alpha7.41 progressive Agile publication."""

from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha741_partial_publication.py"
DASHBOARD = KEMS / "dashboard_alpha741_partial_publication.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha741-progressive-agile-publication.md"


def test_alpha741_contract_is_coordinated_in_alpha8() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.0"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.0"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.0"


def test_alpha741_modules_parse() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))
    ast.parse(DASHBOARD.read_text(encoding="utf-8"))


def test_alpha741_installs_after_alpha740() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha741_partial_publication_patch" in loader
    assert "install_alpha741_partial_publication_dashboard_patch" in loader
    assert loader.rindex(
        "install_alpha741_partial_publication_patch()"
    ) > loader.rindex("install_alpha740_opportunity_guard_patch()")
    assert loader.rindex(
        "install_alpha741_partial_publication_dashboard_patch()"
    ) > loader.rindex("install_alpha740_agile_primary_dashboard_patch()")


def test_alpha741_accepts_only_clean_publication_pending_gaps() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'diagnostics.get("primary_fetch_status") == "success"' in source
    assert "missing_labels.issubset(primary_missing | unresolved)" in source
    assert 'outcome == "retrieval_error"' in source
    assert "and not retrieval_error" in source
    assert '"publication_pending": True' in source
    assert "known-price dispatch may use the bounded partial" in source


def test_alpha741_never_guesses_missing_prices_and_keeps_reserve() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert (
        '"unknown_price_policy": "reserve full slot capacity; never guess price"'
        in source
    )
    assert (
        '"current_slot_policy": "no deliberate export without a real current price"'
        in source
    )
    assert '"unknown_slot_capacity_reserved_kwh"' in source
    assert "missing_slots_for_day" in source
    assert "rebuild automatically as new Octopus prices arrive" in source


def test_alpha741_publishes_progressive_tomorrow_state() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "sensor.kems_agile_tomorrow_publication_plan" in source
    assert (
        'status = f"Provisional — using {known}/{expected} published prices"' in source
    )
    assert 'status = f"Complete — {known}/{expected} prices"' in source
    assert 'mode = "progressive_known_prices"' in source
    assert 'quality["tomorrow_status"] = str(progressive.get("status"))' in source
    assert 'tomorrow["provisional_price_ready"]' in source


def test_alpha741_dashboard_adds_publication_sensor() -> None:
    improve = runpy.run_path(str(DASHBOARD))["improve_alpha741_dashboard"]
    source = (
        "            title: Forecast evidence\n"
        "            show_header_toggle: false\n"
        "            entities:\n"
        "              - sensor.kems_forecast_solar_tomorrow\n"
    )
    result = improve(source)
    assert "sensor.kems_agile_tomorrow_publication_plan" in result
    assert result.count("sensor.kems_agile_tomorrow_publication_plan") == 1


def test_alpha741_remains_hardware_write_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"hardware_writes": "blocked"' in source
    assert '"real_backend_available": False' in source


def test_alpha741_documentation_records_safety_contract() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.41" in source
    assert "46/48 published" in source
    assert "never substitutes zero" in source
    assert "full discharge opportunity" in source
    assert "10% reserve" in source
    assert "Real hardware writes remain blocked" in source
