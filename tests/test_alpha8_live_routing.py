"""Alpha8 contracts for canonical Alpha7.29 live-routing ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_live_routing.py"
RUNTIME = KEMS / "agile_live_routing_runtime.py"
HISTORICAL = KEMS / "agile_alpha729_live_routing.py"


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


def test_live_routing_retires_alpha729_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "agile_alpha728_bounded_partial",
        "install_alpha728_bounded_partial_horizon_patch",
    )
    canonical = ("agile_live_routing", "install_live_routing")
    following = (
        "agile_alpha730_current_routing",
        "install_alpha730_current_routing_patch",
    )

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name == "agile_alpha729_live_routing" for module_name, _ in specs
    )
    assert HISTORICAL.is_file()


def test_live_routing_runtime_is_byte_identical_to_alpha729() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_live_routing_facade_owns_only_installation() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert "agile_live_routing_runtime" in source
    assert "live_routing_runtime.install_alpha729_live_routing_parity_patch()" in source
    assert "from . import agile_alpha729_live_routing" not in source
    assert "without rewriting" in source


def test_live_routing_preserves_proven_reporting_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        '_LIVE_SENSOR = "sensor.kems_agile_live_scenario"',
        '_HOUSE_SENSOR = "sensor.kems_house_load"',
        'attrs["simulated_house_load_kw"] = simulated_house_kw',
        'attrs["simulated_house_load_basis"] = simulated_basis',
        'attrs["live_house_load_source"] = _HOUSE_SENSOR',
        'attrs["house_load_parity_available"] = live_house_kw is not None',
        '"simulated elapsed-slot average fallback"',
        'attrs["current_house_load_kw"] = round(live_house_kw, 3)',
        '"reporting_only": True',
        "House demand (live)",
        "Digital-twin slot-average demand",
        "**House-demand basis:**",
        "install_alpha729_live_routing_parity_patch",
    ):
        assert token in source


def test_live_routing_leaves_alpha730_alpha731_coupled_pair_untouched() -> None:
    specs = _compat_specs()
    canonical = ("agile_live_routing", "install_live_routing")
    current = (
        "agile_alpha730_current_routing",
        "install_alpha730_current_routing_patch",
    )
    solar = (
        "agile_alpha731_solar_headroom",
        "install_alpha731_solar_headroom_patch",
    )
    deadline = ("agile_deadline_guard", "install_deadline_guard")

    assert specs.index(canonical) < specs.index(current)
    assert specs.index(current) < specs.index(solar)
    assert specs.index(solar) < specs.index(deadline)

    source = (
        FACADE.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
    )
    assert "agile_alpha730_current_routing" not in source
    assert "agile_alpha731_solar_headroom" not in source


def test_live_routing_cannot_change_dispatch_or_enable_hardware_writes() -> None:
    source = (
        FACADE.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
    )

    assert "_dispatch_targets(" not in source
    assert "rolling_export_plan" not in source
    assert "battery_export_target_kw" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
