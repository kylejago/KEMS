"""Alpha8 contracts for canonical Alpha7.15 history compatibility ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_history_compatibility.py"
RUNTIME = KEMS / "agile_history_compatibility_runtime.py"
HISTORICAL = KEMS / "agile_alpha715_backfill.py"
PREINSTALL_RUNTIME = KEMS / "agile_preinstall_evidence_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-history-compatibility-canonicalisation.md"


def _pre_base_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "PRE_BASE_PATCHES":
            continue
        assert isinstance(node.value, ast.Tuple)
        return [
            (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            for item in node.value.elts
            if isinstance(item, ast.Tuple) and len(item.elts) == 2
        ]
    raise AssertionError("PRE_BASE_PATCHES was not found")


def test_history_compatibility_retires_alpha715_from_live_pre_base_execution() -> None:
    specs = _pre_base_specs()
    enhanced = ("agile_history_backfill_v2", "install_enhanced_backfill")
    canonical = ("agile_history_compatibility", "install_history_compatibility")

    assert specs.index(canonical) == specs.index(enhanced) + 1
    assert not any(module == "agile_alpha715_backfill" for module, _ in specs)
    assert HISTORICAL.is_file()


def test_history_compatibility_runtime_is_byte_identical_to_alpha7_source() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_history_compatibility_facade_needs_no_legacy_module_bridge() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert "history_runtime.install_alpha715_backfill_patch()" in source
    assert "sys.modules" not in source
    assert "agile_alpha715_backfill" not in source


def test_history_runtime_preserves_current_and_legacy_energy_grid_schemas() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        'source.get("flow_from")',
        'source.get("flow_to")',
        '"stat_energy_from"',
        '"stat_energy_to"',
        "_ORIGINAL_ENERGY_SOURCES(values)",
        "enhanced._energy_sources = _energy_sources_compatible",
    ):
        assert token in source


def test_history_runtime_preserves_diagnostics_and_shutdown_cleanup() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        "sensor.kems_agile_backfill_method",
        "sensor.kems_agile_backfill_reason",
        "sensor.kems_agile_backfill_direct_sources",
        "sensor.kems_agile_backfill_grid_import",
        "sensor.kems_agile_backfill_grid_export",
        "sensor.kems_agile_backfill_solar",
        "sensor.kems_agile_backfill_battery_discharge",
        "sensor.kems_agile_backfill_battery_charge",
        "sensor.kems_agile_backfill_battery_soc",
        "Historical data available",
        "Configured — no usable history yet",
        "self._hass.states.async_remove(entity_id)",
    ):
        assert token in source


def test_preinstall_evidence_consumes_shared_backfill_not_alpha715_module_identity() -> None:
    source = PREINSTALL_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_history_backfill as backfill" in source
    assert "agile_alpha715_backfill" not in source


def test_history_compatibility_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source


def test_historical_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert "install_alpha715_backfill_patch()" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_history_compatibility_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "2a2d1a6afdbf5860b90c28bdab7da209391827c9" in source
    assert "No runtime body is rewritten" in source
    assert "real hardware writes remain blocked" in source
