"""Regression coverage for read-only FoxESS physical commissioning evidence."""

from types import SimpleNamespace

from kems_core.commissioning_evidence import (
    assess_foxess_power_balance,
    assess_foxess_unit_contract,
    compare_shadow_battery_target,
)


def _record(
    *,
    battery_soc: float = 50.0,
    battery_power_kw: float = 1.0,
    solar_power_kw: float = 2.0,
    house_load_kw: float = 2.5,
    grid_import_kw: float = 0.0,
    grid_export_kw: float = 0.5,
    stale_fields: tuple[str, ...] = (),
):
    return SimpleNamespace(
        battery_soc=battery_soc,
        battery_power_kw=battery_power_kw,
        solar_power_kw=solar_power_kw,
        house_load_kw=house_load_kw,
        grid_import_kw=grid_import_kw,
        grid_export_kw=grid_export_kw,
        stale_fields=stale_fields,
    )


def test_direct_foxess_units_match_provider_conversion_contract() -> None:
    """Direct power sources may be W/kW while SOC must be percent."""
    evidence = assess_foxess_unit_contract(
        {
            "battery_soc": "%",
            "battery_power_kw": "W",
            "solar_power_kw": "kW",
            "house_load_kw": "W",
            "grid_import_kw": "kW",
            "grid_export_kw": "W",
        }
    )

    assert evidence.ready is True
    assert evidence.state == "valid"
    assert evidence.missing_fields == ()
    assert evidence.mismatched_fields == ()


def test_derived_battery_power_requires_volts_and_amps() -> None:
    """Voltage/current derivation must reject units KEMS does not normalise."""
    valid = assess_foxess_unit_contract(
        {
            "battery_soc": "%",
            "battery_voltage": "V",
            "battery_current": "A",
            "solar_power_kw": "W",
            "house_load_kw": "W",
            "grid_import_kw": "W",
            "grid_export_kw": "W",
        },
        battery_power_derived=True,
    )
    invalid = assess_foxess_unit_contract(
        {
            "battery_soc": "%",
            "battery_voltage": "V",
            "battery_current": "mA",
            "solar_power_kw": "W",
            "house_load_kw": "W",
            "grid_import_kw": "W",
            "grid_export_kw": "W",
        },
        battery_power_derived=True,
    )

    assert valid.ready is True
    assert invalid.ready is False
    assert invalid.state == "unit_mismatch"
    assert invalid.mismatched_fields == ("battery_current",)


def test_unit_contract_fails_closed_when_metadata_is_missing() -> None:
    """Unknown raw units must stay commissioning evidence, not assumed valid."""
    evidence = assess_foxess_unit_contract(
        {
            "battery_soc": "%",
            "battery_power_kw": "kW",
            "solar_power_kw": "kW",
            "house_load_kw": None,
            "grid_import_kw": "kW",
            "grid_export_kw": "kW",
        }
    )

    assert evidence.ready is False
    assert evidence.state == "unit_missing"
    assert evidence.missing_fields == ("house_load_kw",)


def test_repeated_physical_power_balance_passes_consistent_site_flows() -> None:
    """Solar + import + discharge must reconcile with load + export + charge."""
    records = [_record() for _ in range(12)]

    evidence = assess_foxess_power_balance(
        records,
        positive_is_discharge=True,
    )

    assert evidence.ready is True
    assert evidence.state == "balanced"
    assert evidence.eligible_samples == 12
    assert evidence.balance_percent == 100.0
    assert evidence.maximum_absolute_residual_kw == 0.0


def test_power_balance_respects_configured_battery_sign_convention() -> None:
    """The same physical discharge must reconcile under the configured sign."""
    records = [_record(battery_power_kw=-1.0) for _ in range(12)]

    evidence = assess_foxess_power_balance(
        records,
        positive_is_discharge=False,
    )

    assert evidence.ready is True
    assert evidence.state == "balanced"


def test_power_balance_rejects_gross_unit_or_direction_mismatch() -> None:
    """A persistent physical imbalance must fail closed for commissioning."""
    records = [_record(house_load_kw=8.0) for _ in range(12)]

    evidence = assess_foxess_power_balance(
        records,
        positive_is_discharge=True,
    )

    assert evidence.ready is False
    assert evidence.state == "power_balance_mismatch"
    assert evidence.balance_percent == 0.0
    assert evidence.maximum_absolute_residual_kw == 5.5


def test_physical_shadow_comparison_is_informational_only() -> None:
    """Physical mismatch is evidence and never permission to write hardware."""
    control = SimpleNamespace(
        desired_charge_power_kw=0.0,
        desired_total_discharge_power_kw=3.0,
    )
    snapshot = _record(battery_power_kw=1.0)

    comparison = compare_shadow_battery_target(
        control,
        snapshot,
        positive_is_discharge=True,
    )

    assert comparison.available is True
    assert comparison.informational_only is True
    assert comparison.target_net_discharge_kw == 3.0
    assert comparison.observed_net_discharge_kw == 1.0
    assert comparison.difference_kw == -2.0
    assert comparison.within_tolerance is False
    assert comparison.observed_direction == "discharge"


def test_physical_shadow_comparison_rejects_stale_battery_data() -> None:
    """Stale battery telemetry must not become valid physical tracking evidence."""
    control = SimpleNamespace(
        desired_charge_power_kw=2.0,
        desired_total_discharge_power_kw=0.0,
    )
    snapshot = _record(
        battery_power_kw=-2.0,
        stale_fields=("battery_power_kw",),
    )

    comparison = compare_shadow_battery_target(
        control,
        snapshot,
        positive_is_discharge=True,
    )

    assert comparison.available is False
    assert comparison.within_tolerance is None
    assert comparison.observed_direction == "unavailable"
