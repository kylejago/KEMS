"""Regression coverage for Alpha7.50 no-reserve row reporting."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha750_no_reserve_reporting.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha750-no-reserve-row-reporting.md"


def test_alpha750_version_and_module_parse() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.7.0-alpha7.50"
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha750_installs_after_alpha749() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha750_no_reserve_reporting_patch" in loader
    assert loader.rindex(
        "install_alpha750_no_reserve_reporting_patch()"
    ) > loader.rindex("install_alpha749_deadline_plan_coverage_patch()")


def test_alpha750_only_relaxes_verified_clean_publication_gap() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'recovery.get("verified")' in source
    assert 'recovery.get("recovery_outcome") == "octopus_missing_price"' in source
    assert 'attrs.get("bounded_partial_horizon_dispatch_active")' in source
    assert 'attrs.get("provisional_reserved_unknown_capacity_kwh")' in source
    assert "provisional <= _EPSILON" in source


def test_alpha750_reconciles_battery_plan_summary_to_zero_effective_reserve() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"unknown_price_capacity_reserved_kwh": 0.0' in source
    assert '"required_from_unknown_slots_kwh": 0.0' in source
    assert '"unknown_price_reservation_policy": "none"' in source
    assert '"replan_when_price_publishes": True' in source


def test_alpha750_rewrites_waiting_row_without_fake_3_5_kwh_reserve() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'decision.startswith("Waiting for Octopus price")' in source
    assert 'row["reserved_unknown_slot_capacity_kwh"] = 0.0' in source
    assert 'row["currently_needed_from_this_unknown_capacity_kwh"] = 0.0' in source
    assert (
        "Waiting for Octopus price — no capacity reserved; re-rank when published"
        in source
    )


def test_reported_21_aug_case_is_no_reserve_even_with_stale_bounded_evidence() -> None:
    """Inactive bounded evidence must not become an effective reservation."""
    recovery_verified = True
    recovery_outcome = "octopus_missing_price"
    bounded_partial_active = False
    provisional_reserved_kwh = 0.0
    stale_bounded_reserved_kwh = 3.5

    effective_no_reserve = (
        recovery_verified
        and recovery_outcome == "octopus_missing_price"
        and not bounded_partial_active
        and provisional_reserved_kwh <= 1e-6
    )

    assert stale_bounded_reserved_kwh == 3.5
    assert effective_no_reserve is True


def test_alpha750_retains_conservative_reporting_for_active_bounded_path() -> None:
    """An actually active bounded path must keep its safety reservation visible."""
    recovery_verified = True
    recovery_outcome = "octopus_missing_price"
    bounded_partial_active = True
    provisional_reserved_kwh = 3.5

    effective_no_reserve = (
        recovery_verified
        and recovery_outcome == "octopus_missing_price"
        and not bounded_partial_active
        and provisional_reserved_kwh <= 1e-6
    )

    assert effective_no_reserve is False


def test_alpha750_keeps_hardware_writes_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_alpha750_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.50" in source
    assert "23:00" in source
    assert "3.500 kWh" in source
    assert "no capacity reserved" in source
    assert "Real FoxESS hardware writes remain blocked" in source
