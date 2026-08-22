"""Alpha8 contracts for canonical Agile price-publication ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_price_publication.py"
RUNTIME = KEMS / "agile_price_publication_runtime.py"
DASHBOARD_RUNTIME = KEMS / "dashboard_price_publication_runtime.py"
HISTORICAL_RUNTIME = KEMS / "agile_alpha741_partial_publication.py"
HISTORICAL_DASHBOARD = KEMS / "dashboard_alpha741_partial_publication.py"


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


def test_price_publication_retires_both_alpha741_modules_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "dashboard_alpha740_agile_primary",
        "install_alpha740_agile_primary_dashboard_patch",
    )
    canonical = ("agile_price_publication", "install_price_publication")
    following = ("agile_operator_telemetry", "install_operator_telemetry")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name
        in {
            "agile_alpha741_partial_publication",
            "dashboard_alpha741_partial_publication",
        }
        for module_name, _ in specs
    )
    assert HISTORICAL_RUNTIME.is_file()
    assert HISTORICAL_DASHBOARD.is_file()


def test_price_publication_runtime_owners_are_byte_identical_to_alpha741() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL_RUNTIME.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_price_publication_facade_preserves_runtime_then_dashboard_order() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    runtime_call = "price_runtime.install_alpha741_partial_publication_patch()"
    dashboard_call = (
        "dashboard_runtime.install_alpha741_partial_publication_dashboard_patch()"
    )
    assert runtime_call in source
    assert dashboard_call in source
    assert source.index(runtime_call) < source.index(dashboard_call)
    assert "agile_alpha741_partial_publication" not in source
    assert "dashboard_alpha741_partial_publication" not in source


def test_price_publication_keeps_bounded_known_price_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'diagnostics.get("primary_fetch_status") == "success"' in source
    assert 'outcome == "retrieval_error"' in source
    assert '"publication_pending": True' in source
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


def test_price_publication_keeps_sensor_and_dashboard_contract() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    dashboard = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    assert "sensor.kems_agile_tomorrow_publication_plan" in runtime
    assert "sensor.kems_agile_tomorrow_publication_plan" in dashboard
    assert (
        'status = f"Provisional — using {known}/{expected} published prices"' in runtime
    )
    assert 'status = f"Complete — {known}/{expected} prices"' in runtime
    assert "Forecast evidence" in dashboard


def test_price_publication_cannot_change_dispatch_or_enable_hardware_writes() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FACADE, RUNTIME, DASHBOARD_RUNTIME)
    )

    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source
    assert '"real_backend_available": False' in source
    assert "real FoxESS hardware writes remain blocked" in source
