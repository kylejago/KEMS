"""Alpha8 contracts for canonical enhanced history-backfill ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_history_backfill_enhancement.py"
RUNTIME = KEMS / "agile_history_backfill_enhancement_runtime.py"
HISTORICAL = KEMS / "agile_history_backfill_v2.py"
HISTORY_COMPAT = KEMS / "agile_history_compatibility_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-history-backfill-enhancement-canonicalisation.md"


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


def test_enhanced_backfill_retires_v2_from_live_pre_base_registry() -> None:
    specs = _pre_base_specs()
    reporting = ("agile_smart_export_reporting", "install_reporting_patch")
    deadline = ("agile_deadline_dispatch", "install_deadline_patch")
    enhanced = (
        "agile_history_backfill_enhancement",
        "install_history_backfill_enhancement",
    )
    compatibility = (
        "agile_history_compatibility",
        "install_history_compatibility",
    )

    assert specs[:4] == [reporting, deadline, enhanced, compatibility]
    assert not any(module == "agile_history_backfill_v2" for module, _ in specs)


def test_enhanced_backfill_runtime_is_byte_identical() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_facade_bridges_v2_name_to_canonical_runtime() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert (
        '_bind_legacy_name("agile_history_backfill_v2", enhancement_runtime)'
        in source
    )
    assert "sys.modules[qualified] = module" in source
    assert "setattr(_PACKAGE, name, module)" in source
    assert "enhancement_runtime.install_enhanced_backfill()" in source


def test_frozen_alpha715_compatibility_uses_bridged_v2_object() -> None:
    source = HISTORY_COMPAT.read_text(encoding="utf-8")

    assert "from . import agile_history_backfill_v2 as enhanced" in source
    assert "current_sources = enhanced._energy_sources" in source
    assert "enhanced._energy_sources = _energy_sources_compatible" in source


def test_enhanced_backfill_behavior_contract_is_preserved() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        "class EnhancedAgileHistoryBackfill(base.AgileHistoryBackfill)",
        '"direct_power_statistics"',
        '"energy_dashboard_counters"',
        '"recorder",',
        '"get_statistics",',
        '"period": "hour"',
        "base.MIN_DAY_COVERAGE",
        '"hourly Home Assistant Energy dashboard energy statistics"',
        "target._async_refresh = enhanced_refresh",
    ):
        assert token in source


def test_energy_schema_compatibility_still_follows_enhancement() -> None:
    specs = _pre_base_specs()
    enhanced = (
        "agile_history_backfill_enhancement",
        "install_history_backfill_enhancement",
    )
    compatibility = (
        "agile_history_compatibility",
        "install_history_compatibility",
    )

    assert specs.index(compatibility) == specs.index(enhanced) + 1


def test_recorder_calls_remain_read_only_statistics_queries() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert source.count("self._hass.services.async_call(") == 2
    assert source.count('"recorder",') >= 2
    assert source.count('"get_statistics",') >= 2
    assert '"blocking":' not in source


def test_enhanced_backfill_cannot_enable_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "permitted"' not in source


def test_historical_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert HISTORICAL.is_file()
    assert "install_enhanced_backfill()" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_enhanced_backfill_docs_record_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "58a4f238f499faa916e91c39760f71839a066c7f" in source
    assert "agile_history_backfill_v2" in source
    assert "real hardware writes remain blocked" in source
