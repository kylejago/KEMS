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
