"""Reward ROI audit is proof-oriented, idempotent and non-controlling."""

from datetime import UTC, datetime
from types import SimpleNamespace

from kems_core.roi_reward_audit import build_reward_audit

NOW = datetime(2026, 11, 4, 7, 50, tzinfo=UTC)
START = "2026-11-01T12:00:00+00:00"
END = "2026-11-01T13:00:00+00:00"


def event(session_id, end, verified=True):
    return SimpleNamespace(
        available=True,
        session_id=session_id,
        session_start=datetime.fromisoformat(end).replace(hour=17, minute=30),
        session_end=datetime.fromisoformat(end),
        physical_export_verified=verified,
        physical_grid_export_kwh=3.268 if verified else None,
        rewardable_reduction_kwh=None,
    )


def test_first_hour_has_joined_id_but_second_hour_remains_unvalued():
    result = build_reward_audit(
        {
            f"{START}|{END}": {
                "day": "2026-11-01",
                "pence": 261.729143,
                "basis": "completed_meter_and_tariff_verified_hour",
                "supplier_settled": False,
            }
        },
        {
            "8090": {
                "day": "2026-11-02",
                "pence": 56,
                "basis": "meter_supported_modelled_power_down_bonus",
                "supplier_settled": False,
            }
        },
        [
            {
                "start": START,
                "end": END,
                "event_id": "8067",
                "booking_source": "octopus_joined_events",
            },
            {
                "start": END,
                "end": "2026-11-01T14:00:00+00:00",
                "event_id": "8068",
                "booking_source": "octopus_joined_events",
            },
        ],
        [event("8135", "2026-11-03T18:30:00+00:00")],
        now=NOW,
        commissioning_date=datetime(2026, 9, 12, tzinfo=UTC).date(),
    )
    assert result["included_count"] == 2
    assert result["included_happy_hour_pence"] == 261.729143
    assert result["included_power_down_pence"] == 56
    assert result["included_total_pence"] == 317.729143
    assert result["unsettled_total_pence"] == 317.729143
    assert result["pending_count"] == 2
    included = [e for e in result["entries"] if e["included_in_roi"]]
    pending = [e for e in result["entries"] if not e["included_in_roi"]]
    assert {(e["type"], e["event_id"]) for e in included} == {
        ("happy_hour", "8067"),
        ("power_down", "8090"),
    }
    assert {e["event_id"] for e in pending} == {"8068", "8135"}
    assert all(e["supplier_status"] == "unsettled" for e in result["entries"])
    assert all("fixed_export_income" not in e for e in result["entries"])


def test_missing_booking_match_does_not_invent_event_id():
    result = build_reward_audit(
        {
            f"{START}|{END}": {
                "day": "2026-11-01",
                "pence": 100,
                "basis": "completed_meter_and_tariff_verified_hour",
                "supplier_settled": False,
            }
        },
        {},
        [],
        [],
        now=NOW,
        commissioning_date=NOW.date(),
    )
    assert result["included_count"] == 0
    assert result["entries"][0]["event_id"] is None


def test_trimmed_rows_do_not_trim_financial_totals():
    result = build_reward_audit(
        {},
        {
            "one": {"day": "2026-11-03", "pence": 20},
            "two": {"day": "2026-11-03", "pence": 30},
        },
        [],
        [],
        now=NOW,
        commissioning_date=datetime(2026, 9, 12).date(),
        max_entries=1,
    )
    assert result["included_total_pence"] == 50
    assert result["entries_omitted"] == 1
    assert len(result["entries"]) == 1


def test_unconfirmed_bookings_never_become_roi_income():
    result = build_reward_audit(
        {},
        {},
        [
            {
                "start": START,
                "end": END,
                "event_id": "guess",
                "booking_source": "public_available_events",
            }
        ],
        [],
        now=NOW,
        commissioning_date=NOW.date(),
    )
    assert result["entries"] == []
    assert result["included_total_pence"] == 0
