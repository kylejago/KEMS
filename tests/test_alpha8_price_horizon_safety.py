"""Alpha8 contracts for canonical Alpha7.22 price-horizon safety ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_price_horizon_safety.py"
RUNTIME = KEMS / "agile_price_horizon_safety_runtime.py"
HISTORICAL = KEMS / "agile_alpha722_horizon.py"
PROVISIONAL_RUNTIME = KEMS / "agile_provisional_planning_runtime.py"
SHADOW_RUNTIME = KEMS / "agile_shadow_command_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-price-horizon-safety-canonicalisation.md"


def _compat_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"PRE_BASE_PATCHES", "POST_BASE_PATCHES"}:
            continue
        assert isinstance(node.value, ast.Tuple)
        for item in node.value.elts:
            assert isinstance(item, ast.Tuple) and len(item.elts) == 2
            specs.append(
                (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            )
    return specs


def test_price_horizon_safety_retires_alpha722_from_execution() -> None:
    specs = _compat_specs()
    dashboard = ("agile_preinstall_evidence", "install_preinstall_dashboard")
    horizon = ("agile_price_horizon_safety", "install_price_horizon_safety")
    shadow = ("agile_shadow_outcome", "install_shadow_command")

    assert specs.index(dashboard) < specs.index(horizon)
    assert specs.index(horizon) < specs.index(shadow)
    assert not any(module_name == "agile_alpha722_horizon" for module_name, _ in specs)
    assert HISTORICAL.is_file()


def test_price_horizon_runtime_is_byte_identical_to_alpha7_source() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_facade_bridges_frozen_alpha722_import_to_canonical_runtime() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert (
        '_bind_legacy_name("agile_alpha722_horizon", price_horizon_runtime)' in source
    )
    assert "price_horizon_runtime.install_alpha722_price_horizon_patch()" in source
    assert "from . import agile_alpha722_horizon" not in source


def test_frozen_provisional_runtime_mutates_the_bridged_alpha722_object() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    provisional = PROVISIONAL_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha722_horizon as alpha722" in provisional
    assert "current_hold = alpha722._hold_price_optimised_export" in provisional
    assert (
        "alpha722._hold_price_optimised_export = "
        "_provisional_hold_price_optimised_export" in provisional
    )
    assert "alpha722_original_hold(state, plan, horizon, now=now)" in provisional
    assert (
        '_bind_legacy_name("agile_alpha722_horizon", price_horizon_runtime)' in facade
    )


def test_price_horizon_runtime_preserves_conservative_dispatch_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        '_DEADLINE_OVERRIDE_MODES = frozenset({"deadline_following", '
        '"maximum_discharge"})',
        "deadline_override = mode in _DEADLINE_OVERRIDE_MODES and current_known",
        'horizon["battery_export_held"] = True',
        'plan["dispatch_mode"] = "price_horizon_hold"',
        'plan["current_battery_export_target_kw"] = 0.0',
        'plan["current_battery_discharge_target_kw"] = round(max(house_kw, 0.0), 3)',
        'plan["selected_slots"] = []',
        'slot["rolling_target_battery_export_kw"] = 0.0',
    ):
        assert token in source


def test_price_horizon_runtime_preserves_readiness_publication() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        'state["live_ready"] = live_ready',
        'state["settlement_ready"] = settlement_ready',
        'status = "Ready — provisional price horizon"',
        '"planning_horizon_missing_labels": horizon.get("missing_labels")',
        '"battery_export_held_for_price_horizon": horizon.get(',
        '"mode": "simulation_only"',
    ):
        assert token in source


def test_shadow_runtime_still_consumes_horizon_evidence_and_blocks_hardware() -> None:
    source = SHADOW_RUNTIME.read_text(encoding="utf-8")

    for token in (
        'plan.get("price_horizon_battery_export_held")',
        'plan.get("price_horizon_complete")',
        'plan.get("price_horizon_deadline_override")',
        '"safe_to_write_hardware": False',
        "commands_permitted=False",
        '"hardware_writes": "blocked"',
        '"real_backend_available": False',
    ):
        assert token in source


def test_price_horizon_canonicalisation_cannot_enable_real_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            RUNTIME.read_text(encoding="utf-8"),
            PROVISIONAL_RUNTIME.read_text(encoding="utf-8"),
            SHADOW_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source


def test_historical_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert "install_alpha722_price_horizon_patch" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_price_horizon_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "a968f1f0ee330fb2df72770cc00d6adc706d0ddf" in source
    assert "No runtime body is rewritten" in source
    assert "real hardware writes remain blocked" in source
