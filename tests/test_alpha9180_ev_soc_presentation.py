"""A genuine vehicle SOC overrides stale Ohme display, not control state."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core.ev_soc_presentation import displayed_ev_soc

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def vehicle(value, age_minutes):
    return SimpleNamespace(
        state=str(value),
        last_reported=NOW - timedelta(minutes=age_minutes),
    )


def test_current_vehicle_soc_is_displayed_instead_of_ohme():
    result = displayed_ev_soc(vehicle(83, 5), 99, now=NOW)
    assert result["value"] == 83
    assert result["source"] == "vehicle"


def test_old_or_invalid_vehicle_soc_falls_back_to_ohme():
    assert displayed_ev_soc(vehicle(83, 400), 99, now=NOW)["value"] == 99
    assert displayed_ev_soc(vehicle("unknown", 1), 99, now=NOW)["value"] == 99
    assert displayed_ev_soc(vehicle(123, 1), 99, now=NOW)["value"] == 99
    assert displayed_ev_soc(None, 99, now=NOW)["source"] == "ohme"


def test_no_known_soc_remains_unknown():
    assert displayed_ev_soc(None, None, now=NOW)["value"] is None
    assert displayed_ev_soc(None, None, now=NOW)["source"] == "unavailable"
