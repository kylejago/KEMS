"""Battery installation authority and telemetry-health evidence.

Alpha9.34 separates three different questions that must never be conflated:

* has the user declared that the physical battery is installed?
* does the mapped battery telemetry look physically credible?
* has battery commissioning proved enough evidence for later control stages?

The explicit installation option is authoritative. Telemetry is advisory while the
battery is not installed and becomes a required health check once it is declared
installed. None of this module grants inverter-write authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping

from .const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_INSTALLED,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    DEFAULT_OPTIONS,
    DOMAIN,
)

NO_BATTERY_VOLTAGE_MAX = 10.0
ZERO_BATTERY_POWER_TOLERANCE_KW = 0.05
ZERO_BATTERY_CURRENT_TOLERANCE_A = 0.1


@dataclass(frozen=True, slots=True)
class BatteryTelemetryAssessment:
    """One explicit battery-installation/telemetry assessment."""

    state: str
    healthy: bool | None
    detail: str
    soc_percent: float | None
    power_kw: float | None
    voltage_v: float | None
    current_a: float | None
    no_battery_sentinel_detected: bool
    setting_telemetry_mismatch: bool

    def to_dict(self) -> dict[str, Any]:
        """Return diagnostics-safe fields."""
        return asdict(self)


def battery_installed_from_options(options: Mapping[str, Any]) -> bool:
    """Return the authoritative physical battery installation setting."""
    return bool(
        options.get(
            CONF_BATTERY_INSTALLED,
            DEFAULT_OPTIONS[CONF_BATTERY_INSTALLED],
        )
    )


def _finite(value: Any) -> float | None:
    """Return one finite float or None."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def assess_battery_values(
    *,
    installed: bool,
    soc_percent: Any,
    power_kw: Any,
    voltage_v: Any,
    current_a: Any,
) -> BatteryTelemetryAssessment:
    """Assess battery telemetry without inferring physical installation.

    A zero SOC is valid by itself. The FoxESS no-battery pattern is instead based
    on near-zero power/current together with near-zero or sentinel battery voltage.
    Once the user declares the battery installed, missing/out-of-range SOC or a
    non-credible battery voltage is a fault and therefore cannot pass commissioning.
    """
    soc = _finite(soc_percent)
    power = _finite(power_kw)
    voltage = _finite(voltage_v)
    current = _finite(current_a)

    sentinel = bool(
        power is not None
        and abs(power) <= ZERO_BATTERY_POWER_TOLERANCE_KW
        and current is not None
        and abs(current) <= ZERO_BATTERY_CURRENT_TOLERANCE_A
        and voltage is not None
        and abs(voltage) <= NO_BATTERY_VOLTAGE_MAX
    )

    credible_soc = soc is not None and 0.0 <= soc <= 100.0
    credible_voltage = voltage is not None and voltage > NO_BATTERY_VOLTAGE_MAX
    telemetry_looks_present = credible_soc and credible_voltage

    if not installed:
        mismatch = telemetry_looks_present and not sentinel
        detail = (
            "Battery is explicitly marked not installed; live battery telemetry is "
            "advisory only."
        )
        if mismatch:
            detail += " Telemetry looks battery-present; review the Battery installed setting."
        elif sentinel:
            detail += " FoxESS is reporting the expected no-battery sentinel pattern."
        return BatteryTelemetryAssessment(
            state="Not expected",
            healthy=None,
            detail=detail,
            soc_percent=soc,
            power_kw=power,
            voltage_v=voltage,
            current_a=current,
            no_battery_sentinel_detected=sentinel,
            setting_telemetry_mismatch=mismatch,
        )

    issues: list[str] = []
    if soc is None:
        issues.append("battery SOC is unavailable/non-numeric")
    elif not 0.0 <= soc <= 100.0:
        issues.append(f"battery SOC {soc:g}% is outside 0-100%")
    if power is None:
        issues.append("battery power is unavailable/non-numeric")
    if current is None:
        issues.append("battery current is unavailable/non-numeric")
    if voltage is None:
        issues.append("battery voltage is unavailable/non-numeric")
    elif voltage <= NO_BATTERY_VOLTAGE_MAX:
        issues.append(
            f"battery voltage {voltage:g} V is a no-battery/sentinel value"
        )

    if issues:
        return BatteryTelemetryAssessment(
            state="Fault",
            healthy=False,
            detail="; ".join(issues),
            soc_percent=soc,
            power_kw=power,
            voltage_v=voltage,
            current_a=current,
            no_battery_sentinel_detected=sentinel,
            setting_telemetry_mismatch=True,
        )

    return BatteryTelemetryAssessment(
        state="Healthy",
        healthy=True,
        detail=(
            "Battery is explicitly marked installed and the mapped SOC, power, "
            "voltage and current are numerically credible. Commissioning evidence "
            "still remains required before control."
        ),
        soc_percent=soc,
        power_kw=power,
        voltage_v=voltage,
        current_a=current,
        no_battery_sentinel_detected=sentinel,
        setting_telemetry_mismatch=False,
    )


def _state_value(hass, entity_id: str | None) -> Any:
    """Return one raw Home Assistant state value without treating zero as missing."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable"}:
        return None
    return state.state


def battery_telemetry_snapshot(
    hass,
    mappings: Mapping[str, str],
    *,
    installed: bool,
) -> BatteryTelemetryAssessment:
    """Assess the currently mapped battery telemetry."""
    return assess_battery_values(
        installed=installed,
        soc_percent=_state_value(hass, mappings.get(CONF_BATTERY_SOC)),
        power_kw=_state_value(hass, mappings.get(CONF_BATTERY_POWER)),
        voltage_v=_state_value(hass, mappings.get(CONF_BATTERY_VOLTAGE)),
        current_a=_state_value(hass, mappings.get(CONF_BATTERY_CURRENT)),
    )


def _battery_installed_from_hass(hass) -> bool:
    """Read the single KEMS config entry's explicit installation option."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return bool(DEFAULT_OPTIONS[CONF_BATTERY_INSTALLED])
    return battery_installed_from_options(entries[0].options)


def _recompute_commissioning_state(payload: dict[str, Any]) -> None:
    """Recompute top-level readiness after adding the telemetry-health contract."""
    checks = payload["checks"]
    required = [item for item in checks if item["required"]]
    payload["fail_count"] = sum(item["status"] == "FAIL" for item in checks)
    payload["wait_count"] = sum(item["status"] == "WAIT" for item in checks)
    payload["pass_count"] = sum(item["status"] == "PASS" for item in checks)
    payload["required_checks"] = len(required)

    required_fail = any(item["status"] == "FAIL" for item in required)
    required_wait = any(item["status"] == "WAIT" for item in required)
    if required_fail:
        state = "Blocked"
    elif not payload.get("foxess_registered_entity_count"):
        state = "Awaiting FoxESS"
    elif required_wait:
        state = "Commissioning"
    else:
        state = "Ready for Shadow"
    payload["state"] = state
    payload["ready_for_shadow"] = state == "Ready for Shadow"
    payload["ready_for_control"] = False
    payload["real_hardware_writes"] = "blocked"


_contract_installed = False


def install_battery_installation_contract() -> None:
    """Make the explicit option authoritative in commissioning diagnostics.

    KEMS is a single-config-entry integration. The wrapper is deliberately narrow:
    it changes installation authority and adds one required telemetry-health check.
    Existing battery sign, stability, power-balance and hardware-write gates remain
    untouched.
    """
    global _contract_installed
    if _contract_installed:
        return

    from . import commissioning

    base_build_snapshot = commissioning.build_commissioning_snapshot

    def _explicit_battery_installation_pending(hass, mappings) -> bool:
        del mappings
        return not _battery_installed_from_hass(hass)

    def _build_commissioning_snapshot(hass, coordinator) -> dict[str, Any]:
        payload = base_build_snapshot(hass, coordinator)
        installed = battery_installed_from_options(coordinator.entry.options)
        assessment = battery_telemetry_snapshot(
            hass,
            coordinator.entities.as_dict(),
            installed=installed,
        )

        if not installed:
            telemetry_check = commissioning._check(
                "battery_telemetry_health",
                "Battery telemetry health",
                "WAIT",
                assessment.detail,
                required=False,
            )
            commissioning_status = "Installation pending"
        elif assessment.healthy:
            telemetry_check = commissioning._check(
                "battery_telemetry_health",
                "Battery telemetry health",
                "PASS",
                assessment.detail,
            )
            commissioning_status = (
                "Telemetry proof complete"
                if payload.get("foxess_telemetry_proof_ready")
                else "Commissioning"
            )
        else:
            telemetry_check = commissioning._check(
                "battery_telemetry_health",
                "Battery telemetry health",
                "FAIL",
                assessment.detail,
            )
            commissioning_status = "Telemetry fault"

        checks = payload["checks"]
        insert_at = next(
            (
                index + 1
                for index, item in enumerate(checks)
                if item["key"] == "foxess_connected"
            ),
            0,
        )
        checks.insert(insert_at, telemetry_check)

        payload["battery_installed"] = installed
        payload["battery_installation_source"] = "explicit_setting"
        payload["battery_installation_status"] = (
            "Installed" if installed else "Not installed"
        )
        payload["battery_telemetry_health"] = assessment.to_dict()
        payload["battery_commissioning_status"] = commissioning_status
        payload["battery_setting_telemetry_mismatch"] = (
            assessment.setting_telemetry_mismatch
        )
        _recompute_commissioning_state(payload)
        return payload

    commissioning._battery_installation_pending = _explicit_battery_installation_pending
    commissioning.build_commissioning_snapshot = _build_commissioning_snapshot
    _contract_installed = True
