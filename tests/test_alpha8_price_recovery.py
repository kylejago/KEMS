"""Alpha8 contracts for canonical Alpha7.27 price-recovery ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_price_recovery.py"
RUNTIME = KEMS / "agile_price_recovery_runtime.py"
HISTORICAL = KEMS / "agile_alpha727_price_recovery.py"
BOUNDED = KEMS / "agile_alpha728_bounded_partial.py"


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


def test_price_recovery_retires_alpha727_from_execution() -> None:
    specs = _compat_specs()
    previous = (
        "agile_alpha726_provisional",
        "install_alpha726_provisional_planning_patch",
    )
    canonical = ("agile_price_recovery", "install_price_recovery")
    following = (
        "agile_alpha728_bounded_partial",
        "install_alpha728_bounded_partial_horizon_patch",
    )

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name == "agile_alpha727_price_recovery" for module_name, _ in specs
    )
    assert HISTORICAL.is_file()
    assert BOUNDED.is_file()


def test_price_recovery_runtime_is_byte_identical_to_alpha727() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_price_recovery_facade_owns_only_installation() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert "agile_price_recovery_runtime" in source
    assert "price_recovery_runtime.install_alpha727_price_recovery_patch()" in source
    assert "from . import agile_alpha727_price_recovery" not in source
    assert "without rewriting" in source


def test_price_recovery_preserves_proven_recovery_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    for token in (
        "MAX_TARGETED_RATE_RETRIES = 4",
        "CONTEXT_PADDING = timedelta(minutes=30)",
        "alpha726.alpha726_original_fetch_rates(self, records, now)",
        'request_kind="exact_half_hour"',
        'request_kind="context_window"',
        "_matching_results(context_results, start, end)",
        '"recovered_exact"',
        '"recovered_context"',
        '"octopus_missing_price"',
        '"octopus_slot_not_published"',
        '"octopus_no_results"',
        '"retrieval_error"',
        '"primary_fetch_error"',
        'state["price_fetch_diagnostics"] = diagnostics',
        "self._kems_alpha727_price_fetch_diagnostics = diagnostics",
        "self._kems_alpha726_rate_fetch_diagnostics = diagnostics",
    ):
        assert token in source


def test_price_recovery_leaves_alpha728_historical_consumer_untouched() -> None:
    specs = _compat_specs()
    canonical = ("agile_price_recovery", "install_price_recovery")
    bounded = (
        "agile_alpha728_bounded_partial",
        "install_alpha728_bounded_partial_horizon_patch",
    )
    source = BOUNDED.read_text(encoding="utf-8")

    assert specs.index(canonical) < specs.index(bounded)
    assert 'getattr(self, "_kems_alpha727_price_fetch_diagnostics", None)' in source
    assert "from . import agile_alpha727_price_recovery" not in source
    assert "install_alpha728_bounded_partial_horizon_patch" in source


def test_price_recovery_cannot_enable_real_hardware_writes() -> None:
    source = (
        FACADE.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source
    assert "never permits FoxESS hardware writes" in source
