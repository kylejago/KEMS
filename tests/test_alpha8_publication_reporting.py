"""Parity contracts for canonical Alpha8 publication-gap reporting."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CANONICAL = KEMS / "agile_publication_reporting.py"


def test_canonical_publication_reporting_parses() -> None:
    ast.parse(CANONICAL.read_text(encoding="utf-8"), filename=str(CANONICAL))


def test_current_day_clean_publication_gap_keeps_no_reserve_contract() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert 'recovery.get("verified")' in source
    assert 'recovery.get("recovery_outcome") == "octopus_missing_price"' in source
    assert 'attrs.get("bounded_partial_horizon_dispatch_active")' in source
    assert 'attrs.get("provisional_reserved_unknown_capacity_kwh")' in source
    assert '"unknown_price_capacity_reserved_kwh": 0.0' in source
    assert '"required_from_unknown_slots_kwh": 0.0' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert '"replan_when_price_publishes": True' in source
    assert (
        "Waiting for Octopus price — no capacity reserved; re-rank when published"
        in source
    )


def test_tomorrow_partial_publication_keeps_no_reserve_and_failure_guards() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert 'progressive.get("provisional")' in source
    assert 'progressive.get("known_price_count")' in source
    assert 'progressive.get("missing_price_count")' in source
    assert 'state.get("last_error") not in (None, "")' in source
    assert 'diagnostics.get("primary_fetch_status")' in source
    assert '== "retrieval_error"' in source
    assert '"unknown_slot_capacity_reserved_kwh": 0.0' in source
    assert '"no_reserve_progressive_tomorrow": True' in source


def test_sub_tolerance_reporting_residual_still_normalises_to_full_coverage() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert "_REPORTING_TOLERANCE_KWH = 0.01" in source
    assert '"unaccounted_export_requirement_kwh": 0.0' in source
    assert '"known_price_plan_coverage_percent": 100.0' in source
    assert '"target_covered": True' in source
    assert '"reporting_residual_normalised": True' in source
    assert "(reserve or 0.0) > _EPSILON" in source
    assert "(required_unknown or 0.0) > _EPSILON" in source


def test_canonicalisation_leaves_dispatch_and_hardware_permissions_out_of_scope() -> (
    None
):
    source = CANONICAL.read_text(encoding="utf-8")
    assert "battery_export_target_kw" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
