"""Regression coverage for alpha7.22 Agile price-horizon safety."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
HORIZON = INTEGRATION / "agile_price_horizon.py"
PATCH = INTEGRATION / "agile_alpha722_horizon.py"
LOADER = INTEGRATION / "agile_smart_export_runtime.py"

spec = importlib.util.spec_from_file_location("agile_price_horizon", HORIZON)
assert spec is not None and spec.loader is not None
horizon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(horizon)

LONDON = ZoneInfo("Europe/London")


def _slot(start: datetime) -> dict[str, str]:
    return {
        "valid_from": start.astimezone(UTC).isoformat(),
        "valid_to": (start + timedelta(minutes=30)).astimezone(UTC).isoformat(),
    }


def test_alpha722_price_horizon_patch_remains_packaged() -> None:
    """Later alpha7 releases must keep the alpha7.22 safety wrapper installed."""
    source = PATCH.read_text(encoding="utf-8")
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha722_price_horizon_patch" in source
    assert "install_alpha722_price_horizon_patch" in loader


def test_expected_price_slots_follow_uk_dst_days() -> None:
    """The pure horizon helper must preserve 46/48/50-slot UK days."""
    assert len(horizon.expected_slots_for_day(date(2026, 3, 29), LONDON)) == 46
    assert len(horizon.expected_slots_for_day(date(2026, 8, 19), LONDON)) == 48
    assert len(horizon.expected_slots_for_day(date(2026, 10, 25), LONDON)) == 50


def test_missing_slots_are_named_without_being_invented() -> None:
    """Missing end-of-day prices must remain explicit gaps."""
    expected = horizon.expected_slots_for_day(date(2026, 8, 19), LONDON)
    present = [
        {
            "valid_from": item["valid_from"],
            "valid_to": item["valid_to"],
        }
        for item in expected
        if item["label"] not in {"23:00", "23:30"}
    ]
    missing = horizon.missing_slots_for_day(
        present,
        date(2026, 8, 19),
        LONDON,
    )
    assert [item["label"] for item in missing] == ["23:00", "23:30"]


def test_remaining_horizon_only_requires_slots_before_cheap_deadline() -> None:
    """A missing 23:30 price must not block battery export ending at 23:30."""
    expected = horizon.expected_slots_for_day(date(2026, 8, 19), LONDON)
    present = [
        {
            "valid_from": item["valid_from"],
            "valid_to": item["valid_to"],
        }
        for item in expected
        if item["label"] != "23:30"
    ]
    now = datetime(2026, 8, 19, 9, 30, tzinfo=LONDON)
    deadline = datetime(2026, 8, 19, 23, 30, tzinfo=LONDON)
    result = horizon.remaining_price_horizon(
        present,
        now=now,
        deadline=deadline,
        timezone=LONDON,
    )
    assert result["complete"] is True
    assert result["missing_count"] == 0
    assert result["current_slot_known"] is True


def test_missing_2300_price_blocks_remaining_export_horizon() -> None:
    """The last pre-cheap Agile slot is part of the optimisation horizon."""
    expected = horizon.expected_slots_for_day(date(2026, 8, 19), LONDON)
    present = [
        {
            "valid_from": item["valid_from"],
            "valid_to": item["valid_to"],
        }
        for item in expected
        if item["label"] not in {"23:00", "23:30"}
    ]
    now = datetime(2026, 8, 19, 9, 30, tzinfo=LONDON)
    deadline = datetime(2026, 8, 19, 23, 30, tzinfo=LONDON)
    result = horizon.remaining_price_horizon(
        present,
        now=now,
        deadline=deadline,
        timezone=LONDON,
    )
    assert result["complete"] is False
    assert result["missing_count"] == 1
    assert result["missing_slots"][0]["label"] == "23:00"


def test_alpha722_patch_holds_price_optimised_export_but_keeps_deadline_override() -> (
    None
):
    """Unknown future prices block price chasing, not deadline safety."""
    source = PATCH.read_text(encoding="utf-8")
    assert '"price_horizon_hold"' in source
    assert '"current_battery_export_target_kw"] = 0.0' in source
    assert "_DEADLINE_OVERRIDE_MODES" in source
    assert '"deadline_following"' in source
    assert '"maximum_discharge"' in source
    assert "and current_known" in source
    assert "hold battery export" in source


def test_alpha722_publishes_live_vs_settlement_readiness() -> None:
    """Incomplete full-day prices must not look like a dead Agile runtime."""
    source = PATCH.read_text(encoding="utf-8")
    assert '"live_ready"' in source
    assert '"settlement_ready"' in source
    assert "Ready — provisional price horizon" in source
    assert "planning_horizon_missing_labels" in source
    assert "sensor.kems_agile_price_horizon_status" in source


def test_alpha722_patch_is_installed_after_existing_agile_dispatch_patches() -> None:
    """The final safety wrapper must see the rolling/deadline dispatch targets."""
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha722_price_horizon_patch" in loader
    assert loader.rindex("install_alpha722_price_horizon_patch()") > loader.rindex(
        "install_alpha717_dispatch_patch()"
    )
