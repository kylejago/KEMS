"""Alpha8 contracts for canonical Alpha7.30/Alpha7.31 routing ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_routing.py"
CURRENT_RUNTIME = KEMS / "agile_current_routing_runtime.py"
SOLAR_RUNTIME = KEMS / "agile_solar_headroom_runtime.py"
HISTORICAL_CURRENT = KEMS / "agile_alpha730_current_routing.py"
HISTORICAL_SOLAR = KEMS / "agile_alpha731_solar_headroom.py"
DEADLINE_RUNTIME = KEMS / "agile_deadline_guard_runtime.py"


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


def test_routing_retires_alpha730_alpha731_from_execution() -> None:
    specs = _compat_specs()
    live = ("agile_live_routing", "install_live_routing")
    current = ("agile_routing", "install_current_routing")
    solar = ("agile_routing", "install_solar_headroom")
    deadline = ("agile_deadline_guard", "install_deadline_guard")

    assert specs.index(live) < specs.index(current)
    assert specs.index(current) < specs.index(solar)
    assert specs.index(solar) < specs.index(deadline)

    retired = {
        "agile_alpha730_current_routing",
        "agile_alpha731_solar_headroom",
    }
    assert not any(module_name in retired for module_name, _ in specs)
    assert HISTORICAL_CURRENT.is_file()
    assert HISTORICAL_SOLAR.is_file()


def test_current_routing_runtime_is_byte_identical_to_alpha730() -> None:
    assert CURRENT_RUNTIME.read_bytes() == HISTORICAL_CURRENT.read_bytes()


def test_solar_headroom_runtime_is_byte_identical_to_alpha731() -> None:
    assert SOLAR_RUNTIME.read_bytes() == HISTORICAL_SOLAR.read_bytes()


def test_routing_facade_bridges_frozen_import_names_to_canonical_objects() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    current_alias = (
        '_bind_legacy_name("agile_alpha730_current_routing", current_runtime)'
    )
    solar_import = "from . import agile_solar_headroom_runtime as solar_runtime"
    solar_alias = '_bind_legacy_name("agile_alpha731_solar_headroom", solar_runtime)'

    assert source.index(current_alias) < source.index(solar_import)
    assert source.index(solar_import) < source.index(solar_alias)
    assert "current_runtime.install_alpha730_current_routing_patch()" in source
    assert "solar_runtime.install_alpha731_solar_headroom_patch()" in source
    assert "from . import agile_alpha730_current_routing" not in source
    assert "from . import agile_alpha731_solar_headroom" not in source


def test_solar_headroom_still_patches_the_alpha730_object_contract() -> None:
    source = SOLAR_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "from . import agile_alpha730_current_routing as alpha730",
        "current_snapshot = alpha730._snapshot",
        "alpha730._snapshot = _snapshot_with_solar_aware_routing",
        "card = alpha730._CURRENT_ROUTING_CARD",
        "alpha730._CURRENT_ROUTING_CARD = card.replace(",
        "dispatch = alpha717._dispatch_targets",
        "rolling_plan = rolling._rolling_plan",
        "build_shadow = alpha723.build_agile_shadow_command",
        '"basis": "Feed-in First solar AC before battery discharge"',
        '"solar_to_battery_kw_while_discharging": 0.0',
        "inverter_headroom = max(config.inverter_limit_kw - routed_solar_ac, 0.0)",
    ):
        assert token in source


def test_deadline_guard_frozen_alpha731_import_resolves_through_bridge() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    deadline = DEADLINE_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha731_solar_headroom as alpha731" in deadline
    assert "alpha731._proposal_solar_evidence(self, config)" in deadline
    assert '_bind_legacy_name("agile_alpha731_solar_headroom", solar_runtime)' in facade


def test_routing_preserves_reporting_dispatch_and_hardware_boundaries() -> None:
    current = CURRENT_RUNTIME.read_text(encoding="utf-8")
    solar = SOLAR_RUNTIME.read_text(encoding="utf-8")
    facade = FACADE.read_text(encoding="utf-8")
    source = "\n".join((facade, current, solar))

    assert '"routing_basis": "current coordinator routing snapshot"' in current
    assert '"battery_candidate_basis": "exact current Agile rolling target"' in current
    assert '"reporting_only": True' in current
    assert '"hardware_writes": "blocked"' in current
    assert "alpha717._dispatch_targets = _dispatch_targets_with_solar_headroom" in solar
    assert (
        "alpha723.build_agile_shadow_command = _build_shadow_with_solar_aware_ac"
        in solar
    )
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
