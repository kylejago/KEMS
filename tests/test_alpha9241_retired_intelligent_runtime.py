"""Legacy Intelligent options must not grant live daytime cheap tariff authority."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

KEMS = Path(__file__).resolve().parents[1] / "custom_components" / "kems"


def _node(name: str) -> ast.AST:
    tree = ast.parse((KEMS / "__init__.py").read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def test_main_setup_retires_saved_true_before_source_validation_and_coordinator() -> None:
    source = (KEMS / "__init__.py").read_text(encoding="utf-8")
    setup = ast.get_source_segment(source, _node("async_setup_entry"))
    assert setup is not None
    assert "legacy_intelligent_retired = options.get(CONF_INTELLIGENT_SLOTS_ENABLED) is True" in setup
    assert "options[CONF_INTELLIGENT_SLOTS_ENABLED] = False" in setup
    assert "hass.config_entries.async_update_entry(entry, options=options)" in setup
    assert setup.index("options[CONF_INTELLIGENT_SLOTS_ENABLED] = False") < setup.index(
        "consolidate_octopus_sources(original_entities)"
    )


def test_old_schema_migration_never_rearms_intelligent_tariff() -> None:
    source = (KEMS / "__init__.py").read_text(encoding="utf-8")
    migration = ast.get_source_segment(source, _node("async_migrate_entry"))
    assert migration is not None
    assert "options.setdefault(CONF_INTELLIGENT_SLOTS_ENABLED, False)" in migration
    assert "options.setdefault(CONF_INTELLIGENT_SLOTS_ENABLED, True)" not in migration
    assert "options[CONF_INTELLIGENT_SLOTS_ENABLED] = False" in migration


def test_source_consolidation_retires_only_unverifiable_legacy_roles() -> None:
    path = KEMS / "kems_core" / "octopus_source_consolidation.py"
    spec = importlib.util.spec_from_file_location("kems_retired_source_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = {
        "intelligent_slot": "binary_sensor.octopus_intelligent_invalid",
        "next_offpeak_start": "sensor.old_next",
        "offpeak_end": "sensor.old_end",
        "off_peak": "binary_sensor.octopus_energy_electricity_off_peak",
        "current_import_rate": "sensor.octopus_energy_import_rate",
        "ev_power_kw": "sensor.ohme_power",
    }
    new = module.consolidate_octopus_sources(old)
    assert new == {
        "off_peak": old["off_peak"],
        "current_import_rate": old["current_import_rate"],
        "ev_power_kw": old["ev_power_kw"],
    }
    assert module.consolidate_octopus_sources(new) == new
