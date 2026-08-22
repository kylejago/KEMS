"""Alpha8 ownership contracts for bounded partial-horizon dispatch."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
REGISTRY = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_bounded_partial.py"
RUNTIME = KEMS / "agile_bounded_partial_runtime.py"
HISTORICAL = KEMS / "agile_alpha728_bounded_partial.py"
DOWNSTREAM = KEMS / "agile_solar_headroom_runtime.py"
HISTORICAL_LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "alpha8-bounded-partial-canonicalisation.md"


def test_alpha8_bounded_partial_replaces_live_alpha728_registry_entry() -> None:
    source = REGISTRY.read_text(encoding="utf-8")
    canonical = '("agile_bounded_partial", "install_bounded_partial_horizon")'
    historical = "agile_alpha728_bounded_partial"
    previous = '("agile_price_recovery", "install_price_recovery")'
    following = '("agile_live_routing", "install_live_routing")'

    assert canonical in source
    assert historical not in source
    assert source.index(previous) < source.index(canonical) < source.index(following)


def test_alpha8_bounded_partial_runtime_is_byte_identical_to_alpha728() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL.read_bytes()


def test_alpha8_bounded_partial_facade_is_installation_only() -> None:
    source = FACADE.read_text(encoding="utf-8")
    assert "agile_bounded_partial_runtime as bounded_partial_runtime" in source
    assert "install_alpha728_bounded_partial_horizon_patch()" in source
    assert "_rolling_plan" not in source
    assert "evaluate_agile_shadow_command" not in source
    assert ".services.async_call(" not in source


def test_alpha8_bounded_partial_preserves_dispatch_and_proof_contract() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    for token in (
        "alpha726._future_missing_capacity_kwh",
        "alpha717._dispatch_targets(",
        "alpha725._candidate_applied_replay(result, config)",
        'safety.get("passed_checks") == 13',
        'tracking.get("tracking_score_percent") == 100.0',
        '"bounded_unknown_slot_dispatch_blocked": True',
        '"dispatch_basis": "bounded_partial_horizon"',
    ):
        assert token in source


def test_alpha8_bounded_partial_keeps_shared_object_chaining_for_alpha731() -> None:
    bounded = RUNTIME.read_text(encoding="utf-8")
    downstream = DOWNSTREAM.read_text(encoding="utf-8")

    assert "rolling._rolling_plan = _rolling_plan_with_alpha728" in bounded
    assert (
        "alpha723.evaluate_agile_shadow_command = "
        "_evaluate_with_bounded_nonzero_proof" in bounded
    )
    assert "from . import agile_rolling_replan as rolling" in downstream
    assert "from . import agile_alpha723_shadow as alpha723" in downstream
    assert "agile_alpha728_bounded_partial" not in downstream


def test_alpha8_bounded_partial_historical_evidence_remains_non_executable() -> None:
    assert HISTORICAL.exists()
    loader = HISTORICAL_LOADER.read_text(encoding="utf-8")
    assert "install_alpha728_bounded_partial_horizon_patch" in loader
    assert "ALPHA7_COMPATIBILITY_ORDER" in loader


def test_alpha8_bounded_partial_remains_hardware_write_blocked() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert 'result["safe_to_write_hardware"] = False' in source
    assert '"hardware_writes": "blocked"' in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_alpha8_bounded_partial_documentation_records_ownership_only() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "exact historical Alpha7.28 Git blob" in source
    assert "ownership migration" in source
    assert "Later solar-headroom installation" in source
    assert "real hardware writes remain blocked" in source
