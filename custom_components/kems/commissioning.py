"""Commissioning-readiness assessment for KEMS shadow control."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_SOLAR_POWER,
)
from .entity import KEMSEntity
from .panel import PANEL_CONFIG_VERSION, panel_health_snapshot

PASS = "PASS"
WAIT = "WAIT"
FAIL = "FAIL"
FOXESS_PLATFORM = "foxess_modbus"


def _check(
    key: str,
    label: str,
    status: str,
    detail: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    """Return one stable commissioning checklist item."""
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "required": required,
    }


def _entity_platform(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Return the integration platform that owns an entity."""
    if not entity_id:
        return None
    registry_entry = er.async_get(hass).async_get(entity_id)
    return registry_entry.platform if registry_entry is not None else None


def _entity_available(hass: HomeAssistant, entity_id: str | None) -> bool:
    """Return whether one Home Assistant source currently has a usable state."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state not in {"unknown", "unavailable"}


def _source_check(
    hass: HomeAssistant,
    mappings: Mapping[str, str],
    key: str,
    label: str,
) -> dict[str, Any]:
    """Require a live FoxESS mapping for one commissioning source."""
    entity_id = mappings.get(key)
    if not entity_id:
        return _check(key, label, WAIT, "No source mapped yet")

    platform = _entity_platform(hass, entity_id)
    if platform != FOXESS_PLATFORM:
        return _check(
            key,
            label,
            WAIT,
            f"Using {platform or 'unknown'} fallback: {entity_id}; waiting for FoxESS Modbus",
        )
    if not _entity_available(hass, entity_id):
        return _check(key, label, FAIL, f"FoxESS source is unavailable: {entity_id}")
    return _check(key, label, PASS, f"{entity_id} ({platform})")


def _battery_power_source_check(
    hass: HomeAssistant,
    mappings: Mapping[str, str],
) -> dict[str, Any]:
    """Accept direct battery power or a live FoxESS voltage/current derivation."""
    direct = mappings.get(CONF_BATTERY_POWER)
    if direct and _entity_platform(hass, direct) == FOXESS_PLATFORM:
        if _entity_available(hass, direct):
            return _check(
                "battery_power_mapping", "Battery power mapping", PASS, direct
            )
        return _check(
            "battery_power_mapping",
            "Battery power mapping",
            FAIL,
            f"FoxESS battery power source is unavailable: {direct}",
        )

    voltage = mappings.get(CONF_BATTERY_VOLTAGE)
    current = mappings.get(CONF_BATTERY_CURRENT)
    if (
        voltage
        and current
        and _entity_platform(hass, voltage) == FOXESS_PLATFORM
        and _entity_platform(hass, current) == FOXESS_PLATFORM
    ):
        if _entity_available(hass, voltage) and _entity_available(hass, current):
            return _check(
                "battery_power_mapping",
                "Battery power mapping",
                PASS,
                f"Derived from {voltage} × {current}",
            )
        return _check(
            "battery_power_mapping",
            "Battery power mapping",
            FAIL,
            "FoxESS voltage/current derivation is configured but unavailable",
        )

    return _check(
        "battery_power_mapping",
        "Battery power mapping",
        WAIT,
        "Waiting for FoxESS battery power or battery voltage/current sources",
    )


def _detect_battery_power_convention(
    records: tuple[Any, ...],
) -> tuple[bool | None, int, float]:
    """Infer whether positive battery power means discharge from SOC movement."""
    recent = records[-360:]
    positive_is_discharge_votes = 0
    positive_is_charge_votes = 0

    for earlier, later in zip(recent, recent[1:], strict=False):
        earlier_soc = getattr(earlier, "battery_soc", None)
        later_soc = getattr(later, "battery_soc", None)
        earlier_power = getattr(earlier, "battery_power_kw", None)
        later_power = getattr(later, "battery_power_kw", None)
        if None in {earlier_soc, later_soc, earlier_power, later_power}:
            continue
        try:
            gap = (later.timestamp - earlier.timestamp).total_seconds()
        except (AttributeError, TypeError):
            continue
        if gap <= 0 or gap > 20 * 60:
            continue

        delta_soc = float(later_soc) - float(earlier_soc)
        average_power = (float(earlier_power) + float(later_power)) / 2.0
        if abs(delta_soc) < 0.2 or abs(average_power) < 0.25:
            continue

        positive_is_discharge = (delta_soc < 0 and average_power > 0) or (
            delta_soc > 0 and average_power < 0
        )
        if positive_is_discharge:
            positive_is_discharge_votes += 1
        else:
            positive_is_charge_votes += 1

    total = positive_is_discharge_votes + positive_is_charge_votes
    if total < 2:
        return None, total, 0.0

    dominant = max(positive_is_discharge_votes, positive_is_charge_votes)
    confidence = round(100.0 * dominant / total, 1)
    if confidence < 75.0:
        return None, total, confidence
    return positive_is_discharge_votes > positive_is_charge_votes, total, confidence


def _foxess_registered_entities(hass: HomeAssistant) -> list[str]:
    """Return currently available entities owned by FoxESS Modbus."""
    registry = er.async_get(hass)
    result: list[str] = []
    for registry_entry in registry.entities.values():
        if registry_entry.platform != FOXESS_PLATFORM:
            continue
        if getattr(registry_entry, "disabled_by", None) is not None:
            continue
        if _entity_available(hass, registry_entry.entity_id):
            result.append(registry_entry.entity_id)
    return sorted(result)


def build_commissioning_snapshot(hass: HomeAssistant, coordinator) -> dict[str, Any]:
    """Build the complete read-only commissioning readiness payload."""
    data = coordinator.data
    mappings = coordinator.entities.as_dict()
    panel = panel_health_snapshot(hass)
    foxess_registered = _foxess_registered_entities(hass)
    foxess_mappings = {
        key: entity_id
        for key, entity_id in sorted(mappings.items())
        if _entity_platform(hass, entity_id) == FOXESS_PLATFORM
    }

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "data_quality",
            "Data quality",
            (
                PASS
                if data.quality.score >= 95.0 and not data.quality.stale_fields
                else FAIL
            ),
            f"{data.quality.score:.0f}% quality; {len(data.quality.stale_fields)} stale field(s)",
        )
    )
    checks.append(
        _check(
            "tariff_data",
            "Tariff data",
            (
                PASS
                if data.snapshot.current_import_rate is not None
                and not data.snapshot.tariff_stale_fields
                else FAIL
            ),
            (
                f"Current import {data.snapshot.current_import_rate} p/kWh; "
                f"cheap period confirmed={data.snapshot.cheap_period_confirmed}"
            ),
        )
    )
    checks.append(
        _check(
            "forecast_engine",
            "Forecast engine",
            PASS if data.forecast.ready and data.forecast_plan.ready else WAIT,
            (
                f"{data.forecast.source}; plan={data.forecast_plan.state}; "
                f"confidence={data.forecast_plan.confidence_percent:.1f}%"
            ),
        )
    )
    checks.append(
        _check(
            "foxess_connected",
            "FoxESS connected",
            PASS if foxess_registered else WAIT,
            (
                f"{len(foxess_registered)} available FoxESS Modbus entities"
                if foxess_registered
                else "Waiting for commissioned FoxESS Modbus entities"
            ),
        )
    )

    checks.append(
        _source_check(hass, mappings, CONF_BATTERY_SOC, "Battery SOC mapping")
    )
    battery_power_check = _battery_power_source_check(hass, mappings)
    checks.append(battery_power_check)
    checks.append(
        _source_check(hass, mappings, CONF_SOLAR_POWER, "Solar power mapping")
    )
    checks.append(
        _source_check(hass, mappings, CONF_GRID_IMPORT, "Grid import mapping")
    )
    checks.append(
        _source_check(hass, mappings, CONF_GRID_EXPORT, "Grid export mapping")
    )
    checks.append(_source_check(hass, mappings, CONF_HOUSE_LOAD, "House load mapping"))

    records = tuple(getattr(getattr(coordinator, "_history", None), "records", ()))
    detected_positive_is_discharge, direction_samples, direction_confidence = (
        _detect_battery_power_convention(records)
    )
    configured_positive_is_discharge = bool(
        coordinator.settings.simulation.battery_power_positive_is_discharge
    )
    if battery_power_check["status"] != PASS:
        battery_direction = _check(
            "battery_power_direction",
            "Battery power direction",
            WAIT,
            "Battery power must be mapped before direction can be verified",
        )
    elif detected_positive_is_discharge is None:
        battery_direction = _check(
            "battery_power_direction",
            "Battery power direction",
            WAIT,
            (
                "Waiting for SOC movement while battery power is above 0.25 kW "
                f"({direction_samples} evidence sample(s))"
            ),
        )
    elif detected_positive_is_discharge == configured_positive_is_discharge:
        convention = (
            "positive = discharge"
            if detected_positive_is_discharge
            else "positive = charge"
        )
        battery_direction = _check(
            "battery_power_direction",
            "Battery power direction",
            PASS,
            f"Observed {convention}; {direction_confidence:.1f}% confidence",
        )
    else:
        observed = (
            "positive = discharge"
            if detected_positive_is_discharge
            else "positive = charge"
        )
        configured = (
            "positive = discharge"
            if configured_positive_is_discharge
            else "positive = charge"
        )
        battery_direction = _check(
            "battery_power_direction",
            "Battery power direction",
            FAIL,
            f"Observed {observed}, but KEMS is configured as {configured}",
        )
    checks.append(battery_direction)

    grid_mapping_ready = all(
        next(item["status"] == PASS for item in checks if item["key"] == key)
        for key in (CONF_GRID_IMPORT, CONF_GRID_EXPORT)
    )
    grid_import = data.snapshot.grid_import_kw
    grid_export = data.snapshot.grid_export_kw
    if not grid_mapping_ready:
        grid_direction_check = _check(
            "grid_direction",
            "Grid direction / normalisation",
            WAIT,
            "Waiting for live FoxESS import and export mappings",
        )
    elif grid_import is None or grid_export is None:
        grid_direction_check = _check(
            "grid_direction",
            "Grid direction / normalisation",
            FAIL,
            "Mapped FoxESS grid values are unavailable after normalisation",
        )
    elif (
        grid_import < -0.01
        or grid_export < -0.01
        or (grid_import > 0.2 and grid_export > 0.2)
    ):
        grid_direction_check = _check(
            "grid_direction",
            "Grid direction / normalisation",
            FAIL,
            (
                f"Implausible normalised flow import={grid_import:.3f} kW, "
                f"export={grid_export:.3f} kW"
            ),
        )
    else:
        grid_direction_check = _check(
            "grid_direction",
            "Grid direction / normalisation",
            PASS,
            (
                f"mode={data.snapshot.grid_flow_mode}; import={grid_import:.3f} kW; "
                f"export={grid_export:.3f} kW"
            ),
        )
    checks.append(grid_direction_check)

    limits = {
        "inverter_limit_kw": data.simulation.inverter_limit_kw,
        "battery_charge_limit_kw": data.simulation.battery_charge_limit_kw,
        "battery_discharge_limit_kw": data.simulation.battery_discharge_limit_kw,
        "export_limit_kw": data.simulation.export_limit_kw,
        "eps_output_limit_kw": data.simulation.eps_output_limit_kw,
        "site_import_limit_kw": data.control.site_import_limit_kw,
    }
    kh7_limits = [
        value
        for key, value in limits.items()
        if key not in {"eps_output_limit_kw", "site_import_limit_kw"}
    ]
    kh7_limits_safe = bool(kh7_limits) and all(
        value is not None and 0 < float(value) <= 7.0 for value in kh7_limits
    )
    checks.append(
        _check(
            "kh7_limits",
            "KH7 limits configured",
            PASS if kh7_limits_safe else FAIL,
            (
                f"inverter={limits['inverter_limit_kw']} kW; charge={limits['battery_charge_limit_kw']} kW; "
                f"discharge={limits['battery_discharge_limit_kw']} kW; export={limits['export_limit_kw']} kW"
            ),
        )
    )
    eps_limit = limits["eps_output_limit_kw"]
    checks.append(
        _check(
            "eps_limit",
            "EPS limit configured",
            PASS if eps_limit is not None and 0 < float(eps_limit) <= 7.0 else FAIL,
            f"EPS output limit={eps_limit} kW",
        )
    )
    site_import_limit = limits["site_import_limit_kw"]
    checks.append(
        _check(
            "site_import_limit",
            "Site import limit confirmed",
            (
                PASS
                if site_import_limit is not None and float(site_import_limit) > 0
                else WAIT
            ),
            (
                f"Configured site limit={site_import_limit} kW"
                if site_import_limit is not None
                else "Waiting for installer/DNO-confirmed site import limit"
            ),
        )
    )

    shadow_safe = (
        data.control.plan_safe
        and data.control.data_fresh
        and data.control.preflight_total > 0
        and data.control.preflight_passed == data.control.preflight_total
    )
    checks.append(
        _check(
            "shadow_planner",
            "Shadow planner",
            PASS if shadow_safe else FAIL,
            (
                f"preflight={data.control.preflight_passed}/{data.control.preflight_total}; "
                f"next={data.control.next_action}"
            ),
        )
    )
    checks.append(
        _check(
            "emergency_stop",
            "Emergency stop",
            FAIL if coordinator.settings.control.emergency_stop else PASS,
            (
                "Emergency stop is engaged"
                if coordinator.settings.control.emergency_stop
                else "Available and not engaged"
            ),
        )
    )
    checks.append(
        _check(
            "real_write_lock",
            "Real hardware write lock",
            PASS if not data.control.commands_permitted else FAIL,
            (
                "Real inverter writes remain hard-blocked in this commissioning PR"
                if not data.control.commands_permitted
                else "Unexpected: control commands are currently permitted"
            ),
        )
    )

    checks.append(
        _check(
            "export_tariff",
            "Paid export tariff",
            PASS if data.simulation.export_tariff_active else WAIT,
            data.simulation.export_tariff_status,
            required=False,
        )
    )
    checks.append(
        _check(
            "panel_managed",
            "Panel managed",
            PASS if panel["managed"] else WAIT,
            f"Automatic OTA armed={panel['automatic_ota_armed']}",
            required=False,
        )
    )
    checks.append(
        _check(
            "panel_ota",
            "Panel OTA / firmware",
            PASS if panel["reported_version"] == PANEL_CONFIG_VERSION else WAIT,
            (
                f"reported={panel['reported_version']}; expected={PANEL_CONFIG_VERSION}; status={panel['status']}"
            ),
            required=False,
        )
    )

    required = [item for item in checks if item["required"]]
    fail_count = sum(item["status"] == FAIL for item in checks)
    wait_count = sum(item["status"] == WAIT for item in checks)
    pass_count = sum(item["status"] == PASS for item in checks)
    required_fail = any(item["status"] == FAIL for item in required)
    required_wait = any(item["status"] == WAIT for item in required)

    if required_fail:
        state = "Blocked"
    elif not foxess_registered:
        state = "Awaiting FoxESS"
    elif required_wait:
        state = "Commissioning"
    else:
        state = "Ready for Shadow"

    return {
        "state": state,
        "ready_for_shadow": state == "Ready for Shadow",
        "ready_for_control": False,
        "maximum_allowed_stage": "shadow",
        "real_hardware_writes": "blocked",
        "pass_count": pass_count,
        "wait_count": wait_count,
        "fail_count": fail_count,
        "required_checks": len(required),
        "checks": checks,
        "foxess_registered_entity_count": len(foxess_registered),
        "foxess_registered_entities": foxess_registered,
        "foxess_mappings": foxess_mappings,
        "configured_battery_power_positive_is_discharge": configured_positive_is_discharge,
        "detected_battery_power_positive_is_discharge": detected_positive_is_discharge,
        "battery_direction_evidence_samples": direction_samples,
        "battery_direction_confidence_percent": direction_confidence,
        "limits": limits,
        "panel": panel,
        "shadow_command": {
            "operating_mode": data.control.operating_mode,
            "reason": data.control.operating_reason,
            "desired_work_mode": data.control.desired_work_mode,
            "desired_charge_power_kw": data.control.desired_charge_power_kw,
            "desired_battery_to_home_power_kw": data.control.desired_battery_to_home_power_kw,
            "desired_battery_export_power_kw": data.control.desired_battery_export_power_kw,
            "desired_total_discharge_power_kw": data.control.desired_total_discharge_power_kw,
            "desired_min_soc_percent": data.control.desired_min_soc_percent,
            "desired_ev_charging_allowed": data.control.desired_ev_charging_allowed,
            "desired_grid_export_allowed": data.control.desired_grid_export_allowed,
            "blocked_reason": data.control.blocked_reason,
            "next_action": data.control.next_action,
        },
    }


class KEMSCommissioningReadinessSensor(KEMSEntity, SensorEntity):
    """Expose the complete commissioning checklist and shadow readiness."""

    _attr_name = "Commissioning readiness"
    _attr_icon = "mdi:clipboard-check-multiple-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        super().__init__(coordinator, "commissioning_readiness")
        self._hass = hass

    @property
    def native_value(self) -> str:
        return str(build_commissioning_snapshot(self._hass, self.coordinator)["state"])

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        payload = build_commissioning_snapshot(self._hass, self.coordinator)
        return {key: value for key, value in payload.items() if key != "state"}


class KEMSPanelManagementStatusSensor(KEMSEntity, SensorEntity):
    """Expose KEMS-managed ESPHome sync and OTA health."""

    _attr_name = "Panel management status"
    _attr_icon = "mdi:monitor-dashboard"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        super().__init__(coordinator, "panel_management_status")
        self._hass = hass

    @property
    def native_value(self) -> str:
        return str(panel_health_snapshot(self._hass)["status"])

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return panel_health_snapshot(self._hass)


class KEMSPanelFirmwareVersionSensor(KEMSEntity, SensorEntity):
    """Expose the version that the ESP32 actually reported after flashing."""

    _attr_name = "Panel firmware version"
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        super().__init__(coordinator, "panel_firmware_version")
        self._hass = hass

    @property
    def native_value(self) -> str | None:
        value = panel_health_snapshot(self._hass)["reported_version"]
        return str(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        panel = panel_health_snapshot(self._hass)
        return {
            "expected_version": panel["expected_version"],
            "reported_entity_id": panel["reported_entity_id"],
            "managed": panel["managed"],
            "automatic_ota_armed": panel["automatic_ota_armed"],
        }


def build_commissioning_entities(
    hass: HomeAssistant, coordinator
) -> list[SensorEntity]:
    """Return KEMS commissioning and panel-health entities."""
    return [
        KEMSCommissioningReadinessSensor(hass, coordinator),
        KEMSPanelManagementStatusSensor(hass, coordinator),
        KEMSPanelFirmwareVersionSensor(hass, coordinator),
    ]
