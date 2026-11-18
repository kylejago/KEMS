"""Regression tests for Ohme cloud-status lag and charging evidence."""

from __future__ import annotations

import pytest
from kems_core.ohme import combine_charger_evidence, interpret_charger_status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Unplugged", (False, False)),
        ("Plugged in", (True, False)),
        ("Charging", (True, True)),
        ("Finished charging", (True, False)),
        ("Pending approval", (True, False)),
        ("unknown", (None, None)),
        ("unavailable", (None, None)),
    ],
)
def test_official_ohme_statuses(status: str, expected: tuple) -> None:
    assert interpret_charger_status(status) == expected


@pytest.mark.parametrize("status", ["Plugged in", "Unplugged", "unknown", None])
def test_fresh_power_overrides_delayed_or_missing_ohme_status(
    status: str | None,
) -> None:
    assert combine_charger_evidence(
        status=status,
        explicit_connected=False,
        explicit_charging=False,
        power_kw=7.1,
    ) == (True, True)


def test_charging_status_is_protected_during_zero_power_transition() -> None:
    assert combine_charger_evidence(
        status="Charging",
        explicit_connected=None,
        explicit_charging=None,
        power_kw=0.0,
    ) == (True, True)


def test_idle_and_unplugged_states_do_not_block_export() -> None:
    assert combine_charger_evidence(
        status="Plugged in",
        explicit_connected=None,
        explicit_charging=None,
        power_kw=0.0,
    ) == (True, False)
    assert combine_charger_evidence(
        status="Unplugged",
        explicit_connected=None,
        explicit_charging=None,
        power_kw=0.0,
    ) == (False, False)


def test_unknown_status_with_no_power_is_not_assumed_charging() -> None:
    assert combine_charger_evidence(
        status="unknown",
        explicit_connected=None,
        explicit_charging=None,
        power_kw=None,
    ) == (None, None)
