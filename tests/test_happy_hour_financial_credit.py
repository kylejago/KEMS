"""Happy Hour gross billing versus estimated supplier credit."""

from datetime import UTC, datetime, timedelta

from kems_core.happy_hour_financial import estimate_happy_hour_credit


def test_confirmed_rewards_preserve_gross_bill() -> None:
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    hours = [
        {
            "start": (start + timedelta(hours=i)).isoformat(),
            "end": (start + timedelta(hours=i + 1)).isoformat(),
            "import_kwh": kwh,
            "cap_kwh": 16.0,
            "coverage_complete": True,
        }
        for i, kwh in enumerate((7.294, 2.582))
    ]
    bookings = [
        {"start": h["start"], "end": h["end"], "event_id": str(i + 1)}
        for i, h in enumerate(hours)
    ]
    kwargs = dict(
        plan={"reward_hours": hours},
        bookings={"bookings": bookings},
        now=start + timedelta(minutes=90),
        import_rate_pence=35.8828,
        gross_import_cost_pence=704.62,
    )
    result = estimate_happy_hour_credit(**kwargs)
    assert result["credited_import_kwh"] == 9.876
    assert result["estimated_credit_pence"] == round(9.876 * 35.8828, 3)
    assert result["supplier_settled"] is False
    assert kwargs["gross_import_cost_pence"] == 704.62

    hours[0]["import_kwh"] = 20.0
    hours[1]["import_kwh"] = 20.0
    kwargs["gross_import_cost_pence"] = 4000.0
    assert estimate_happy_hour_credit(**kwargs)["credited_import_kwh"] == 32.0

    hours[0]["coverage_complete"] = False
    bookings.pop()
    assert estimate_happy_hour_credit(**kwargs)["estimated_credit_pence"] is None


def test_unbooked_hours_never_get_free_import() -> None:
    assert (
        estimate_happy_hour_credit(
            plan={"reward_hours": []},
            bookings={"bookings": []},
            now=datetime(2026, 11, 1, 13, tzinfo=UTC),
            import_rate_pence=35.8828,
            gross_import_cost_pence=1000.0,
        )["estimated_credit_pence"]
        is None
    )


def test_completed_joined_hours_survive_octopus_live_feed_expiry() -> None:
    """1 Nov: two physically measured hours remain credited after joined expiry."""
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    hours = [
        {
            "start": (start + timedelta(hours=i)).isoformat(),
            "end": (start + timedelta(hours=i + 1)).isoformat(),
            "import_kwh": amount,
            "cap_kwh": 16.0,
            "coverage_complete": True,
        }
        for i, amount in enumerate((7.294, 3.655))
    ]
    # The real physical import recorder stores BOTH one-hour windows while
    # Octopus joined evidence is still present, before its two-hour expiry.
    windows = [{"start": h["start"], "end": h["end"]} for h in hours]
    result = estimate_happy_hour_credit(
        plan={"reward_hours": hours},
        bookings={"bookings": []},
        persisted_confirmed_windows=windows,
        now=start + timedelta(hours=5),
        import_rate_pence=35.8828,
        gross_import_cost_pence=739.76,
    )
    assert result["credited_import_kwh"] == 10.949
    assert result["estimated_credit_pence"] == 392.881
    assert result["verified_reward_hours"] == 2
    assert all(r["completed"] for r in result["verified_hour_receipts"])

    # Completed receipts are immutable even when joined bookings, plan rows,
    # and observed tariff subsequently change or HA restarts.
    restored = estimate_happy_hour_credit(
        plan={},
        bookings={"bookings": []},
        verified_receipts=result["verified_hour_receipts"],
        now=start + timedelta(hours=9),
        import_rate_pence=6.6,
        gross_import_cost_pence=739.76,
    )
    assert restored["credited_import_kwh"] == 10.949
    assert restored["estimated_credit_pence"] == 392.881


def test_expired_joined_hour_does_not_erase_another_verified_hour() -> None:
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    hour_one = {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "import_kwh": 7.294,
        "cap_kwh": 16.0,
        "coverage_complete": True,
    }
    hour_two = {
        "start": (start + timedelta(hours=1)).isoformat(),
        "end": (start + timedelta(hours=2)).isoformat(),
        "import_kwh": 3.655,
        "cap_kwh": 16.0,
        "coverage_complete": True,
    }
    result = estimate_happy_hour_credit(
        plan={"reward_hours": [hour_one, hour_two]},
        bookings={
            "bookings": [
                {"start": hour_two["start"], "end": hour_two["end"], "event_id": "8068"}
            ]
        },
        persisted_confirmed_windows=[
            {"start": hour_one["start"], "end": hour_one["end"]}
        ],
        now=start + timedelta(hours=3),
        import_rate_pence=35.8828,
        gross_import_cost_pence=739.76,
    )
    assert result["credited_import_kwh"] == 10.949
    assert result["estimated_credit_pence"] == 392.881


def test_public_event_or_unfinished_saved_window_cannot_grant_credit() -> None:
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    hour = {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "import_kwh": 7.294,
        "cap_kwh": 16.0,
        "coverage_complete": True,
    }
    kwargs = dict(
        plan={"reward_hours": [hour]},
        bookings={"bookings": []},
        now=start + timedelta(minutes=45),
        import_rate_pence=35.8828,
        gross_import_cost_pence=739.76,
    )
    assert estimate_happy_hour_credit(**kwargs)["estimated_credit_pence"] is None
    assert (
        estimate_happy_hour_credit(
            **kwargs,
            persisted_confirmed_windows=[{"start": hour["start"], "end": hour["end"]}],
        )["estimated_credit_pence"]
        is None
    )
    kwargs["now"] = start + timedelta(hours=3)
    hour["coverage_complete"] = False
    assert (
        estimate_happy_hour_credit(
            **kwargs,
            persisted_confirmed_windows=[{"start": hour["start"], "end": hour["end"]}],
        )["estimated_credit_pence"]
        is None
    )
