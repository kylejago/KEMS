"""Alpha8 contracts for canonical Alpha7.25/Alpha7.26 proof-planning ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_proof_planning.py"
NONZERO_RUNTIME = KEMS / "agile_nonzero_export_proof_runtime.py"
PROVISIONAL_RUNTIME = KEMS / "agile_provisional_planning_runtime.py"
HISTORICAL_NONZERO = KEMS / "agile_alpha725_nonzero.py"
HISTORICAL_PROVISIONAL = KEMS / "agile_alpha726_provisional.py"
PRICE_RECOVERY_RUNTIME = KEMS / "agile_price_recovery_runtime.py"
BOUNDED_RUNTIME = KEMS / "agile_bounded_partial_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-proof-planning-canonicalisation.md"


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


def test_proof_planning_retires_alpha725_alpha726_from_execution() -> None:
    specs = _compat_specs()
    outcome = ("agile_alpha724_outcome", "install_alpha724_outcome_parity_patch")
    nonzero = ("agile_proof_planning", "install_nonzero_export_proof")
    provisional = ("agile_proof_planning", "install_provisional_planning")
    recovery = ("agile_price_recovery", "install_price_recovery")

    assert specs.index(outcome) < specs.index(nonzero)
    assert specs.index(nonzero) < specs.index(provisional)
    assert specs.index(provisional) < specs.index(recovery)

    retired = {"agile_alpha725_nonzero", "agile_alpha726_provisional"}
    assert not any(module_name in retired for module_name, _ in specs)
    assert HISTORICAL_NONZERO.is_file()
    assert HISTORICAL_PROVISIONAL.is_file()


def test_proof_planning_runtimes_are_byte_identical_to_alpha7_sources() -> None:
    assert NONZERO_RUNTIME.read_bytes() == HISTORICAL_NONZERO.read_bytes()
    assert PROVISIONAL_RUNTIME.read_bytes() == HISTORICAL_PROVISIONAL.read_bytes()


def test_proof_planning_facade_bridges_frozen_import_names() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    assert '"agile_alpha725_nonzero", nonzero_runtime' in source
    assert '"agile_alpha726_provisional", provisional_runtime' in source
    assert "nonzero_runtime.install_alpha725_nonzero_export_proof_patch()" in source
    assert "provisional_runtime.install_alpha726_provisional_planning_patch()" in source
    assert "from . import agile_alpha725_nonzero" not in source
    assert "from . import agile_alpha726_provisional" not in source


def test_price_recovery_frozen_alpha726_dependency_resolves_through_bridge() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    recovery = PRICE_RECOVERY_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha726_provisional as alpha726" in recovery
    assert "await alpha726.alpha726_original_fetch_rates(self, records, now)" in recovery
    assert '_bind_legacy_name("agile_alpha726_provisional", provisional_runtime)' in facade


def test_bounded_partial_frozen_helpers_resolve_through_bridge() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    bounded = BOUNDED_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha725_nonzero as alpha725" in bounded
    assert "from . import agile_alpha726_provisional as alpha726" in bounded
    assert "alpha725._candidate_applied_replay(result, config)" in bounded
    assert "alpha726._future_missing_capacity_kwh" in bounded
    assert '_bind_legacy_name("agile_alpha725_nonzero", nonzero_runtime)' in facade
    assert '_bind_legacy_name("agile_alpha726_provisional", provisional_runtime)' in facade


def test_nonzero_runtime_preserves_proven_proof_contract() -> None:
    source = NONZERO_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "NONZERO_EXPORT_THRESHOLD_KW = 0.01",
        "STRICT_TRACKING_TOLERANCE_KW = 0.01",
        'result.get("price_horizon_complete") is True',
        'candidate.get("desired_work_mode") == "Feed-in First"',
        '"independent_safety_13_of_13"',
        'safety.get("passed_checks") == 13',
        'safety.get("total_checks") == 13',
        '"strict_tracking_100_percent"',
        'result["safe_to_write_hardware"] = False',
    ):
        assert token in source


def test_provisional_runtime_preserves_hold_reserve_and_retry_contract() -> None:
    source = PROVISIONAL_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "MAX_TARGETED_RATE_RETRIES = 4",
        "alpha722_original_hold(state, plan, horizon, now=now)",
        'plan["dispatch_permitted_battery_export_kw"] = 0.0',
        'plan["provisional_selected_slots"]',
        'plan["provisional_reserved_unknown_capacity_kwh"]',
        "_future_missing_capacity_kwh",
        "_reserve_unknown_capacity",
        'hold["hold_projected_deadline_soc_percent"]',
        'hold["provisional_projected_deadline_soc_percent"]',
        '"hardware_writes": "blocked"',
    ):
        assert token in source


def test_historical_loader_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert "install_alpha725_nonzero_export_proof_patch" in loader
    assert "install_alpha726_provisional_planning_patch" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.0"' in manifest


def test_proof_planning_cannot_enable_real_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            NONZERO_RUNTIME.read_text(encoding="utf-8"),
            PROVISIONAL_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source


def test_proof_planning_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "e3a5319366ec1d1351e1ee8b18ad7899de432d71" in source
    assert "ff8c3190cb0eeb1801cbfd312fe49d6800fc14e5" in source
    assert "No runtime body is rewritten" in source
    assert "real hardware writes remain blocked" in source
