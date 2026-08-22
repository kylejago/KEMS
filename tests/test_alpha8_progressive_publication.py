"""Parity contracts for canonical Alpha8 progressive publication planning."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CANONICAL = KEMS / "agile_progressive_publication.py"
REPORTING = KEMS / "agile_publication_reporting.py"


def test_canonical_progressive_publication_parses() -> None:
    ast.parse(CANONICAL.read_text(encoding="utf-8"), filename=str(CANONICAL))


def test_plan_clarity_preserves_soc_target_and_coverage_evidence() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "Battery plan to next cheap period" in source
    assert "simulated_soc_percent" in source
    assert "target_soc_percent" in source
    assert "protected_house_energy_kwh" in source
    assert "known_price_planned_export_kwh" in source
    assert "unknown_price_capacity_reserved_kwh" in source
    assert "required_from_unknown_slots_kwh" in source
    assert "unaccounted_export_requirement_kwh" in source
    assert "projected_soc_after_known_plan_percent" in source
    assert "projected_soc_with_reserved_capacity_percent" in source
    assert "target_covered" in source
    assert "unknown_prices_are_never_guessed" in source


def test_clean_publication_gap_keeps_full_known_price_plan_and_zero_reserve() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "def _no_reserve_unknown_capacity(" in source
    assert (
        "return [dict(item) for item in selected if isinstance(item, dict)], 0.0"
        in source
    )
    assert "alpha726._reserve_unknown_capacity = _no_reserve_unknown_capacity" in source
    assert 'recovery.get("verified")' in source
    assert 'recovery.get("recovery_outcome") == "octopus_missing_price"' in source
    assert 'recovery.get("publication_pending")' not in source
    assert 'horizon.get("current_slot_known")' in source
    assert 'current_price.get("known")' in source
    assert '"provisional_reserved_unknown_capacity_kwh": 0.0' in source
    assert '"bounded_unknown_capacity_reserved_kwh": 0.0' in source
    assert '"publication_gap_no_reserve_active": True' in source
    assert '"dispatch_mode": "progressive_known_prices_no_reserve"' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert '"replan_when_price_publishes": True' in source


def test_non_clean_or_unpromoted_path_stays_conservative() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert source.count("_original_bounded_partial_apply(") >= 2
    assert 'plan["provisional_reserved_unknown_capacity_kwh"] = required' in source
    assert 'if not plan.get("bounded_partial_horizon_dispatch_active")' in source
    assert 'plan["provisional_reserved_unknown_capacity_kwh"] = 0.0' in source
    assert (
        "Existing current-price, reserve, deadline, Power Down and Happy Hour" in source
    )


def test_dashboard_keeps_plan_clarity_and_no_reserve_explanation() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert "sensor.kems_battery_state_of_charge" in source
    assert "sensor.kems_agile_simulated_battery_soc_now" in source
    assert "Capacity reserved for unpublished slots | **0.0 kWh**" in source
    assert "Published-price plan coverage" in source
    assert "no capacity reserved; re-rank when" in source
    assert "may replace lower-value future export slots" in source
    assert "_improve_plan_clarity_dashboard(content)" in source
    assert "_improve_dashboard_no_reserve(content)" in source


def test_publication_reporting_now_patches_the_canonical_surface() -> None:
    source = REPORTING.read_text(encoding="utf-8")

    assert "agile_progressive_publication as progressive_publication" in source
    assert "progressive_publication._plan_summary" in source
    assert "progressive_publication._annotate_unknown_slot_rows" in source
    assert "agile_alpha745_plan_clarity" not in source
    assert "agile_alpha746_no_unknown_reserve" not in source


def test_progressive_publication_cannot_enable_hardware_writes() -> None:
    source = CANONICAL.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source
