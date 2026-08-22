"""Alpha8 contracts for canonical Alpha7.34 deadline-guard ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_deadline_guard.py"
RUNTIME = KEMS / "agile_deadline_guard_runtime.py"
HISTORICAL = KEMS / "agile_alpha734_deadline_guard.py"


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


def test_deadline_guard_retires_alpha734_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "agile_alpha731_solar_headroom",
        "install_alpha731_solar_headroom_patch",
    )
    canonical = ("agile_deadline_guard", "install_deadline_guard")
    following = ("agile_cheap_window_handover", "install_cheap_window_handover")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name == "agile_alpha734_deadline_guard" for module_name, _ in specs
    )
    assert HISTORICAL.is_file()


def test_deadline_guard_runtime_is_byte_identical_to_alpha734() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_deadline_guard_facade_owns_only_installation() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert "agile_deadline_guard_runtime" in source
    assert "deadline_runtime.install_alpha734_deadline_guard_patch()" in source
    assert "from . import agile_alpha734_deadline_guard" not in source
    assert "without rewriting" in source


def test_deadline_guard_preserves_proven_policy_and_dependencies() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        "DEADLINE_GUARD_MINUTES = 10",
        "CAPACITY_STEP_MINUTES = 5",
        "_capacity_segments",
        "_latest_safe_start",
        "solar_aware_remaining_capacity_kwh",
        "solar_aware_deadline_margin_kwh",
        "target_physically_reachable_now",
        "skippable_half_hours",
        'mode = "target_reached"',
        'mode = "maximum_discharge"',
        'mode = "deadline_following"',
        'mode = "price_optimised"',
        'evidence.get("battery_inverter_headroom_kw")',
        "max(config.export_limit_kw, 0.0)",
        "max(config.inverter_limit_kw - house_kw, 0.0)",
        "max(config.max_discharge_kw - house_kw, 0.0)",
        "alpha717._dispatch_targets = dispatch_with_alpha734",
        "rolling._rolling_plan = rolling_plan_with_alpha734",
    ):
        assert token in source

    assert "from . import agile_alpha717_dispatch as alpha717" in source
    assert "from . import agile_alpha731_solar_headroom as alpha731" in source
    assert "from . import agile_rolling_replan as rolling" in source


def test_deadline_guard_cannot_enable_real_hardware_writes() -> None:
    source = (
        FACADE.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real hardware writes are still gated" in source
