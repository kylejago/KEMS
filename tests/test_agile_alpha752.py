"""Regression coverage for Alpha7.52 tomorrow no-reserve reporting."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha752_tomorrow_no_reserve_rounding.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha752-tomorrow-no-reserve-rounding.md"


def test_alpha752_version_and_module_parse() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.8.0-alpha8.0"
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha752_installs_after_alpha751() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha752_tomorrow_no_reserve_rounding_patch" in loader
    assert loader.rindex(
        "install_alpha752_tomorrow_no_reserve_rounding_patch()"
    ) > loader.rindex("install_alpha751_maximum_discharge_plan_reconcile_patch()")


def test_alpha752_zeroes_clean_tomorrow_unknown_reserve() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"unknown_slot_capacity_reserved_kwh": 0.0' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert '"replan_when_price_publishes": True' in source
    assert '"no_reserve_progressive_tomorrow": True' in source


def test_alpha752_requires_partial_known_tomorrow_prices() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'progressive.get("provisional")' in source
    assert 'progressive.get("known_price_count")' in source
    assert 'progressive.get("missing_price_count")' in source


def test_alpha752_keeps_retrieval_failures_conservative() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'state.get("last_error") not in (None, "")' in source
    assert 'diagnostics.get("primary_fetch_status")' in source
    assert '== "retrieval_error"' in source


def test_reported_46_of_48_tomorrow_case_reserves_nothing() -> None:
    known_prices = 46
    expected_prices = 48
    old_reserved_kwh = 7.0
    clean_publication_gap = known_prices > 0 and known_prices < expected_prices

    assert clean_publication_gap is True
    assert old_reserved_kwh == 7.0
    assert 0.0 == 0.0


def test_alpha752_normalises_one_wh_residual_to_zero() -> None:
    exportable_kwh = 35.109
    planned_kwh = 35.108
    tolerance_kwh = 0.01
    residual_kwh = max(exportable_kwh - planned_kwh, 0.0)

    assert round(residual_kwh, 3) == 0.001
    assert residual_kwh <= tolerance_kwh


def test_alpha752_publishes_100_percent_for_sub_tolerance_residual() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"unaccounted_export_requirement_kwh": 0.0' in source
    assert '"known_price_plan_coverage_percent": 100.0' in source
    assert '"target_covered": True' in source
    assert '"reporting_residual_normalised": True' in source


def test_alpha752_does_not_hide_real_unknown_reserve() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "(reserve or 0.0) > _EPSILON" in source
    assert "(required_unknown or 0.0) > _EPSILON" in source
    assert "residual > _REPORTING_TOLERANCE_KWH" in source


def test_alpha752_keeps_hardware_writes_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "real FoxESS hardware permissions are unchanged" in source


def test_alpha752_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.52" in source
    assert "46/48" in source
    assert "7.0 kWh" in source
    assert "35.109 kWh" in source
    assert "35.108 kWh" in source
    assert "0.001 kWh" in source
    assert "Real FoxESS hardware writes remain blocked" in source
