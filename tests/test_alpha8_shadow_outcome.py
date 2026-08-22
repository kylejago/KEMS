"""Alpha8 contracts for canonical Alpha7.23/Alpha7.24 shadow ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_shadow_outcome.py"
SHADOW_RUNTIME = KEMS / "agile_shadow_command_runtime.py"
OUTCOME_RUNTIME = KEMS / "agile_outcome_parity_runtime.py"
HISTORICAL_SHADOW = KEMS / "agile_alpha723_shadow.py"
HISTORICAL_OUTCOME = KEMS / "agile_alpha724_outcome.py"
PROOF_RUNTIME = KEMS / "agile_nonzero_export_proof_runtime.py"
BOUNDED_RUNTIME = KEMS / "agile_bounded_partial_runtime.py"
SOLAR_RUNTIME = KEMS / "agile_solar_headroom_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha8-shadow-outcome-canonicalisation.md"


def _compat_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
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


def test_shadow_outcome_retires_alpha723_alpha724_from_execution() -> None:
    specs = _compat_specs()
    horizon = ("agile_price_horizon_safety", "install_price_horizon_safety")
    shadow = ("agile_shadow_outcome", "install_shadow_command")
    outcome = ("agile_shadow_outcome", "install_outcome_parity")
    proof = ("agile_proof_planning", "install_nonzero_export_proof")

    assert specs.index(horizon) < specs.index(shadow)
    assert specs.index(shadow) < specs.index(outcome)
    assert specs.index(outcome) < specs.index(proof)

    retired = {"agile_alpha723_shadow", "agile_alpha724_outcome"}
    assert not any(module_name in retired for module_name, _ in specs)
    assert HISTORICAL_SHADOW.is_file()
    assert HISTORICAL_OUTCOME.is_file()


def test_shadow_outcome_runtimes_are_byte_identical_to_alpha7_sources() -> None:
    assert SHADOW_RUNTIME.read_bytes() == HISTORICAL_SHADOW.read_bytes()
    assert OUTCOME_RUNTIME.read_bytes() == HISTORICAL_OUTCOME.read_bytes()


def test_facade_binds_shadow_before_importing_frozen_outcome_runtime() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    shadow_alias = '_bind_legacy_name("agile_alpha723_shadow", shadow_runtime)'
    outcome_import = "from . import agile_outcome_parity_runtime as outcome_runtime"
    outcome_alias = '_bind_legacy_name("agile_alpha724_outcome", outcome_runtime)'

    assert source.index(shadow_alias) < source.index(outcome_import)
    assert source.index(outcome_import) < source.index(outcome_alias)
    assert "shadow_runtime.install_alpha723_shadow_patch()" in source
    assert "outcome_runtime.install_alpha724_outcome_parity_patch()" in source


def test_outcome_runtime_still_patches_the_alpha723_object_contract() -> None:
    source = OUTCOME_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "from . import agile_alpha723_shadow as alpha723",
        "_ORIGINAL_BUILD = alpha723.build_agile_shadow_command",
        "_ORIGINAL_EVALUATE = alpha723.evaluate_agile_shadow_command",
        "_ORIGINAL_RECORD = alpha723._record_agile_decision",
        "alpha723.build_agile_shadow_command = (",
        "alpha723.evaluate_agile_shadow_command = (",
        "alpha723._record_agile_decision = _record_agile_decision_with_outcome",
    ):
        assert token in source


def test_frozen_proof_runtime_resolves_both_legacy_names_through_facade() -> None:
    facade = FACADE.read_text(encoding="utf-8")
    proof = PROOF_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha723_shadow as alpha723" in proof
    assert "from . import agile_alpha724_outcome as alpha724" in proof
    assert "alpha724._record_agile_decision_with_outcome" in proof
    assert '_bind_legacy_name("agile_alpha723_shadow", shadow_runtime)' in facade
    assert '_bind_legacy_name("agile_alpha724_outcome", outcome_runtime)' in facade


def test_later_frozen_layers_keep_patching_the_same_shadow_object() -> None:
    bounded = BOUNDED_RUNTIME.read_text(encoding="utf-8")
    solar = SOLAR_RUNTIME.read_text(encoding="utf-8")

    assert "from . import agile_alpha723_shadow as alpha723" in bounded
    assert "current_evaluate = alpha723.evaluate_agile_shadow_command" in bounded
    assert "alpha723.evaluate_agile_shadow_command = " in bounded
    assert "from . import agile_alpha723_shadow as alpha723" in solar
    assert "build_shadow = alpha723.build_agile_shadow_command" in solar
    assert (
        "alpha723.build_agile_shadow_command = _build_shadow_with_solar_aware_ac"
        in solar
    )


def test_shadow_runtime_preserves_optimizer_safety_and_hardware_contract() -> None:
    source = SHADOW_RUNTIME.read_text(encoding="utf-8")

    for token in (
        'plan.get("current_battery_export_target_kw")',
        'plan.get("current_battery_discharge_target_kw")',
        "validate_shadow_command(candidate, config)",
        "shadow_plan_vs_outcome(candidate, simulation)",
        '"safe_to_write_hardware": False',
        "commands_permitted=False",
        '"hardware_writes": "blocked"',
        '"real_backend_available": False',
    ):
        assert token in source


def test_outcome_runtime_preserves_routing_and_outcome_contract() -> None:
    source = OUTCOME_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "rolling._current_house_headroom_kw",
        "simulator._simulated_solar_power(current, config)",
        '"same proposal/live solar path as Agile replay"',
        "base_ac) - base_discharge + candidate_discharge",
        "total_kh7_ac_output_kw=round(normalised_ac, 3)",
        'result["outcome_parity_passed"] = outcome_passed',
        'result["status"] = "CHECK — shadow outcome mismatch"',
    ):
        assert token in source


def test_historical_metadata_and_alpha8_version_remain_unchanged() -> None:
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert "install_alpha723_shadow_patch" in loader
    assert "install_alpha724_outcome_parity_patch" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader
    assert '"version": "0.8.0-alpha8.' in manifest


def test_shadow_outcome_cannot_enable_real_hardware_writes() -> None:
    source = "\n".join(
        (
            FACADE.read_text(encoding="utf-8"),
            SHADOW_RUNTIME.read_text(encoding="utf-8"),
            OUTCOME_RUNTIME.read_text(encoding="utf-8"),
        )
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source


def test_shadow_outcome_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "ownership migration only" in source
    assert "d943eb70cb1bccc5f4a0a831ca8be65004228b11" in source
    assert "c5de2199ad657c80b5c2e2a28fcdfed8327074ed" in source
    assert "No runtime body is rewritten" in source
    assert "real hardware writes remain blocked" in source
