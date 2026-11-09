"""Alpha9.191: physical Power Down delivery is not a settled reward."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from custom_components.kems import alpha951_power_down_post_event as reporting
from custom_components.kems.kems_core import PowerDownResult
from kems_core.roi_reward_audit import build_reward_audit

ROOT = Path(__file__).parents[1]


def completed_event(
    *, bonus: float | None = None, status: str = "not_evaluated"
) -> PowerDownResult:
    """Actual 9 November diagnostic; measured and planned values are different."""
    return PowerDownResult(
        available=True,
        session_id="8342",
        session_start=datetime(2026, 11, 9, 17, tzinfo=UTC),
        session_end=datetime(2026, 11, 9, 18, tzinfo=UTC),
        planned_export_kwh=4.883,
        physical_grid_export_kwh=3.973,
        physical_grid_import_kwh=0.0,
        physical_export_verified=True,
        physical_evidence_status="verified_physical_grid_export",
        physical_coverage_hours=0.982,
        physical_samples_observed=57,
        bonus_pence=bonus,
        rewardable_reduction_kwh=None,
        fixed_export_income_pence=58.6,
        reward_evidence_status=status,
        ev_successfully_blocked=True,
        plan_safe_throughout=True,
        completed_successfully=True,
        completion_reason="completed",
        supplier_settled=False,
    )


def test_8342_delivery_verified_but_bonus_unknown_not_zero() -> None:
    event = completed_event()
    shown = reporting._result_dict(event)
    assert shown["session_id"] == "8342"
    assert shown["planned_export_kwh"] == 4.883
    assert shown["physical_grid_export_kwh"] == 3.973
    assert shown["physical_grid_import_kwh"] == 0.0
    assert shown["physical_coverage_percent"] == 98.2
    assert shown["physical_export_verified"] is True
    assert shown["bonus_pence"] is None
    assert shown["bonus_evidence_available"] is False
    assert shown["reward_evidence_status"] == (
        "unvalued_bonus_missing_octopus_net_baseline_or_rate"
    )
    assert shown["supplier_settled"] is False
    assert shown["agile_export_income_already_counted"] is True
    # £0.586 is a *planned-route benchmark*, never an incremental ROI reward.
    assert shown["fixed_export_income_pence"] == 58.6


def test_explicit_baseline_and_rate_status_survive_restart_roundtrip() -> None:
    event = completed_event(status="octopus_net_baseline_unavailable")
    saved = json.loads(json.dumps(event.to_dict()))
    restored = PowerDownResult.from_dict(saved)
    assert restored.reward_evidence_status == "octopus_net_baseline_unavailable"
    assert (
        reporting._result_dict(restored)["reward_evidence_status"]
        == "octopus_net_baseline_unavailable"
    )
    assert restored.bonus_pence is None
    assert restored.physical_grid_export_kwh == 3.973


def test_known_zero_bonus_and_missing_bonus_are_distinct() -> None:
    missing = reporting._result_dict(completed_event())
    known_zero = reporting._result_dict(completed_event(bonus=0.0))
    assert missing["bonus_evidence_available"] is False
    assert known_zero["bonus_evidence_available"] is True
    assert known_zero["bonus_pence"] == 0.0
    assert not known_zero["supplier_settled"]


def test_pending_event_not_added_to_roi_or_counted_again_as_agile_export() -> None:
    audit = build_reward_audit(
        {},
        {},
        [],
        [completed_event()],
        now=datetime(2026, 11, 9, 18, 21, tzinfo=UTC),
        commissioning_date=date(2026, 9, 12),
    )
    assert audit["included_power_down_pence"] == 0.0
    assert audit["included_total_pence"] == 0.0
    assert audit["pending_count"] == 1
    record = audit["entries"][0]
    assert record["event_id"] == "8342"
    assert record["physical_export_verified"] is True
    assert record["physical_grid_export_kwh"] == 3.973
    assert record["modelled_agile_export_income_pence"] == 58.6
    assert record["included_in_roi"] is False
    assert record["estimated_reward_pence"] is None
    assert record["physical_export_coverage_hours"] == 0.982
    assert record["agile_export_income_already_counted"] is True


def test_both_dashboard_sources_never_render_none_as_zero_bonus() -> None:
    card = (ROOT / "custom_components/kems/power_down_dashboard_card.yaml").read_text()
    assert "physical_grid_export_kwh" in card
    assert "physical_coverage_percent" in card
    assert "additional power down bonus" in card.lower()
    assert "item.get('bonus_pence') is not none" in card
    assert "awaiting matched Octopus baseline/rate" in card
    assert "Planned-route export income benchmark" in card
    assert "Supplier settlement" in card
    for path in (
        ROOT / "custom_components/kems/kems_master_dashboard.yaml",
        ROOT / "dashboards/kems_master_dashboard.yaml",
    ):
        config = yaml.safe_load(path.read_text())
        assert config["views"]
        text = path.read_text()
        assert "Last measured event export" in text
        assert "unvalued; matched Octopus baseline/rate required" in text


def test_release_changes_do_not_add_inverter_or_octopus_write_authority() -> None:
    source = (
        ROOT / "custom_components/kems/alpha951_power_down_post_event.py"
    ).read_text()
    assert "async_call(" not in source
    assert "foxess_modbus" not in source
    assert "confirmed_supplier_credit_today_pence" in source
    assert "bonus_evidence_available_today" in source
