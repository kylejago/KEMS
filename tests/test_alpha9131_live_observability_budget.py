"""Alpha9.131 verifies shadow reporting and physical/price audit stay read-only."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from kems_core.agile_plan_budget_reconciliation import reconcile_agile_budget
from kems_core.shadow_validation import shadow_recorder_status

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
AT = "2026-10-24T09:35:56+01:00"


@pytest.mark.parametrize(
    ("mode", "backend", "permitted", "expected"),
    [
        ("control", True, True, "Shadow comparison active — live control permitted"),
        ("control", True, False, "Shadow comparison — live controller not permitted"),
        ("control", False, False, "Shadow comparison — live backend unavailable"),
        ("shadow", False, False, "Shadow active"),
        ("simulate", False, False, "Ready for shadow"),
        ("observe", False, False, "Observe only"),
    ],
)
def test_shadow_status_never_claims_live_block_due_to_shadow_only(
    mode: str, backend: bool, permitted: bool, expected: str
) -> None:
    assert (
        shadow_recorder_status(
            operating_mode=mode,
            emergency_stop=False,
            shadow_safety_passed=True,
            ready=True,
            real_backend_available=backend,
            commands_permitted=permitted,
        )
        == expected
    )


def test_shadow_emergency_and_its_own_safety_do_not_claim_foxess_result() -> None:
    check = dict(
        operating_mode="control",
        emergency_stop=False,
        shadow_safety_passed=False,
        ready=False,
        real_backend_available=True,
        commands_permitted=True,
    )
    assert shadow_recorder_status(**check).startswith("Shadow safety check failed")
    check["emergency_stop"] = True
    assert shadow_recorder_status(**check) == "Emergency stop"


def _budget(
    *,
    target_kw: float = 0.701,
    required_now: float = 0.0,
    scheduled: float = 0.0,
) -> tuple[dict, dict]:
    state = {
        "rolling_export_plan": {
            "available": True,
            "generated_at": AT,
            "physical_planning_evidence": {"available": True},
            "planned_battery_export_kwh": 24.042,
            "protected_house_energy_kwh": 11.431,
            "forecast_solar_to_house_credit_kwh": 5.41,
            "current_battery_export_target_kw": target_kw,
            "required_in_current_slot_kwh": required_now,
            "selected_slots": (
                [
                    {
                        "valid_from": "2026-10-24T09:30:00+01:00",
                        "valid_to": "2026-10-24T10:00:00+01:00",
                        "planned_battery_export_kwh": scheduled,
                    }
                ]
                if scheduled
                else [
                    {
                        "valid_from": "2026-10-24T16:00:00+01:00",
                        "valid_to": "2026-10-24T16:30:00+01:00",
                        "planned_battery_export_kwh": 2.8,
                    }
                ]
            ),
        }
    }
    guard = {
        "physical_energy_evidence": {"observed_at": AT},
        "exportable_physical_energy_kwh": 17.689,
        "protected_home_energy_kwh": 20.056,
        "conservative_solar_credit_kwh": 1.503,
        "permitted_export_kw": 0.701,
        "status": "permitted_with_physical_house_budget",
    }
    return state, guard


def test_actual_morning_mismatch_is_visible_but_does_not_change_authority() -> None:
    state, guard = _budget()
    prior_state, prior_guard = deepcopy(state), deepcopy(guard)
    outcome = reconcile_agile_budget(state, guard)
    assert outcome["status"] == "physical_guard_tighter"
    assert outcome["current_guard_limited_export_ceiling_kwh"] == 17.689
    assert outcome["current_guard_limited_ceiling_is_schedule"] is False
    assert outcome["plan_above_physical_budget_kwh"] == 6.353
    assert outcome["extra_guard_house_protection_kwh"] == 8.625
    assert outcome["planner_solar_house_credit_kwh"] == 5.41
    assert outcome["guard_conservative_solar_credit_kwh"] == 1.503
    assert (
        outcome["current_slot_dispatch_alignment"]["status"]
        == "export_target_outside_selected_slot"
    )
    assert outcome["hardware_writes"] == "blocked"
    assert outcome["dispatch_authority"] == "unchanged_independent_physical_guard"
    assert state == prior_state and guard == prior_guard


@pytest.mark.parametrize(
    ("target_kw", "mandatory", "scheduled"),
    [(0.0, 0.0, 0.0), (0.701, 0.2, 0.0), (0.701, 0.0, 0.35)],
)
def test_zero_export_mandatory_deadline_and_selected_slot_are_not_alerted(
    target_kw: float, mandatory: float, scheduled: float
) -> None:
    outcome = reconcile_agile_budget(
        *_budget(target_kw=target_kw, required_now=mandatory, scheduled=scheduled)
    )
    assert outcome["current_slot_dispatch_alignment"]["status"] == "consistent"


def test_unverified_or_unsynchronised_data_never_gets_a_credible_ceiling() -> None:
    state, guard = _budget()
    guard["physical_energy_evidence"]["observed_at"] = "2026-10-24T09:36:56+01:00"
    assert reconcile_agile_budget(state, guard)["status"] == "unavailable"
    state, guard = _budget()
    state["rolling_export_plan"]["physical_planning_evidence"]["available"] = False
    assert reconcile_agile_budget(state, guard)["status"] == "unavailable"


def test_release_scope_keeps_existing_hardware_and_auto_update_code() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.155"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.155:")
    assert (
        "all live hardware control logic unchanged" in bundle["maintenance"]["reason"]
    )
    assert (
        "current_guard_limited_ceiling_is_schedule"
        in (KEMS / "kems_core/agile_plan_budget_reconciliation.py").read_text()
    )
    assert "real_backend_scope" in (KEMS / "shadow_validation.py").read_text()
