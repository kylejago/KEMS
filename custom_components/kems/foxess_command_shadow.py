"""Read-only Home Assistant adapter for FoxESS command-shadow parity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er

from .kems_core.foxess_command_shadow import build_foxess_command_shadow

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import KEMSCoordinator

FOXESS_PLATFORM = "foxess_modbus"
COMMAND_KEYS = (
    "work_mode",
    "force_charge_power",
    "force_discharge_power",
    "min_soc_on_grid",
    "export_power_limit",
)
COMMAND_DOMAINS = {
    "work_mode": "select",
    "force_charge_power": "number",
    "force_discharge_power": "number",
    "min_soc_on_grid": "number",
    "export_power_limit": "number",
}
UNKNOWN_STATES = {"unknown", "unavailable"}


def _entry_reviewed_key(entry: object) -> str | None:
    """Return the reviewed FoxESS key independent of HA entity domain."""
    if str(getattr(entry, "platform", "")).casefold() != FOXESS_PLATFORM:
        return None
    unique_id = str(getattr(entry, "unique_id", ""))
    for key in COMMAND_KEYS:
        if unique_id == f"foxess_modbus_{key}" or unique_id.endswith(f"_{key}"):
            return key
    return None


def _entry_command_key(entry: object) -> str | None:
    """Return a reviewed key only for its writable select/number domain."""
    key = _entry_reviewed_key(entry)
    if key is None:
        return None
    domain = str(getattr(entry, "entity_id", "")).partition(".")[0].casefold()
    return key if domain == COMMAND_DOMAINS[key] else None


def _entry_readback_key(entry: object) -> str | None:
    """Return a reviewed key for a matching read-only sensor counterpart."""
    key = _entry_reviewed_key(entry)
    if key is None:
        return None
    domain = str(getattr(entry, "entity_id", "")).partition(".")[0].casefold()
    return key if domain == "sensor" else None


def _telemetry_device_ids(
    registry: Any,
    configured_entities: Mapping[str, str],
) -> tuple[str, ...]:
    """Return FoxESS device IDs already authoritative for KEMS telemetry."""
    devices: set[str] = set()
    for entity_id in configured_entities.values():
        entry = registry.async_get(entity_id)
        if (
            entry is not None
            and str(getattr(entry, "platform", "")).casefold() == FOXESS_PLATFORM
            and getattr(entry, "device_id", None)
        ):
            devices.add(str(entry.device_id))
    return tuple(sorted(devices))


def _keyed_candidates(
    entries: Iterable[object],
    device_id: str,
    classifier,
) -> dict[str, tuple[object, ...]]:
    """Return reviewed entities grouped by key on one FoxESS device."""
    grouped: dict[str, list[object]] = {key: [] for key in COMMAND_KEYS}
    for entry in entries:
        if str(getattr(entry, "device_id", "")) != device_id:
            continue
        key = classifier(entry)
        if key is not None:
            grouped[key].append(entry)
    return {
        key: tuple(sorted(values, key=lambda item: str(getattr(item, "entity_id", ""))))
        for key, values in grouped.items()
    }


def _command_candidates(
    entries: Iterable[object],
    device_id: str,
) -> dict[str, tuple[object, ...]]:
    """Return only writable reviewed command entities on one FoxESS device."""
    return _keyed_candidates(entries, device_id, _entry_command_key)


def _readback_candidates(
    entries: Iterable[object],
    device_id: str,
) -> dict[str, tuple[object, ...]]:
    """Return matching read-only sensor evidence on one FoxESS device."""
    return _keyed_candidates(entries, device_id, _entry_readback_key)


def _state_value(
    hass: HomeAssistant,
    entity_id: str,
) -> tuple[object | None, str | None]:
    """Read one HA entity without invoking any service or write path."""
    state = hass.states.get(entity_id)
    if state is None or str(state.state).casefold() in UNKNOWN_STATES:
        return None, None
    return state.state, state.attributes.get("unit_of_measurement")


def _number(value: object) -> float | None:
    """Return a numeric HA state when possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _power_w(value: object, unit: str | None) -> float | None:
    """Normalise a FoxESS export-limit state to its reviewed native W unit."""
    number = _number(value)
    if number is None:
        return None
    normalised_unit = str(unit or "").casefold().replace(" ", "")
    if normalised_unit in {"w", "watt", "watts"}:
        return number
    if normalised_unit in {"kw", "kilowatt", "kilowatts"}:
        return number * 1000
    return None


def build_foxess_command_shadow_snapshot(
    hass: HomeAssistant,
    coordinator: KEMSCoordinator,
) -> dict[str, Any]:
    """Build a deterministic read-only FoxESS command/parity diagnostic."""
    registry = er.async_get(hass)
    configured = coordinator.entities.as_dict()
    telemetry_devices = _telemetry_device_ids(registry, configured)

    if len(telemetry_devices) == 1:
        selected_device = telemetry_devices[0]
        binding_status = "PASS"
        binding_reason = (
            "Command entities are scoped to the FoxESS device already authoritative "
            "for KEMS telemetry"
        )
        candidates = _command_candidates(registry.entities.values(), selected_device)
        readbacks = _readback_candidates(registry.entities.values(), selected_device)
    elif not telemetry_devices:
        selected_device = None
        binding_status = "WAIT"
        binding_reason = (
            "No authoritative FoxESS telemetry device is available for safe "
            "command-entity binding"
        )
        candidates = {key: () for key in COMMAND_KEYS}
        readbacks = {key: () for key in COMMAND_KEYS}
    else:
        selected_device = None
        binding_status = "WAIT"
        binding_reason = (
            "KEMS telemetry resolves to more than one FoxESS device; command "
            "shadow will not guess which inverter owns the command surface"
        )
        candidates = {key: () for key in COMMAND_KEYS}
        readbacks = {key: () for key in COMMAND_KEYS}

    observed: dict[str, object] = {}
    entity_bindings: dict[str, dict[str, Any]] = {}
    ambiguous_keys: list[str] = []

    for key in COMMAND_KEYS:
        matches = candidates[key]
        readback_matches = readbacks[key]
        if len(matches) != 1:
            if len(matches) > 1:
                ambiguous_keys.append(key)
            entity_bindings[key] = {
                "status": "WAIT",
                "entity_id": None,
                "candidate_entity_ids": [
                    str(getattr(item, "entity_id", "")) for item in matches
                ],
                "reason": (
                    "No unique FoxESS command entity found"
                    if len(matches) != 0
                    else "FoxESS command entity is not available on the selected device"
                ),
            }
            continue

        entry = matches[0]
        entity_id = str(entry.entity_id)
        readback_entry = readback_matches[0] if len(readback_matches) == 1 else None
        observation_entry = readback_entry or entry
        observation_entity_id = str(observation_entry.entity_id)
        raw_value, unit = _state_value(hass, observation_entity_id)
        available = raw_value is not None

        if key == "work_mode":
            value = raw_value
            observed_key = "work_mode"
        elif key == "force_charge_power":
            value = _number(raw_value)
            observed_key = "force_charge_power_kw"
        elif key == "force_discharge_power":
            value = _number(raw_value)
            observed_key = "force_discharge_power_kw"
        elif key == "min_soc_on_grid":
            value = _number(raw_value)
            observed_key = "min_soc_on_grid_percent"
        else:
            value = _power_w(raw_value, unit)
            observed_key = "export_power_limit_w"

        if value is not None:
            observed[observed_key] = value

        entity_bindings[key] = {
            "status": "PASS" if available and value is not None else "WAIT",
            "entity_id": entity_id,
            "unique_id": str(getattr(entry, "unique_id", "")),
            "device_id": str(getattr(entry, "device_id", "")),
            "readback_entity_id": (
                str(readback_entry.entity_id) if readback_entry is not None else None
            ),
            "candidate_readback_entity_ids": [
                str(getattr(item, "entity_id", "")) for item in readback_matches
            ],
            "observation_entity_id": observation_entity_id,
            "observation_source": (
                "sensor_readback" if readback_entry is not None else "command_entity"
            ),
            "raw_state": raw_value,
            "unit": unit,
            "normalised_observation": value,
            "reason": (
                "Read-only FoxESS sensor readback observed"
                if available and value is not None and readback_entry is not None
                else (
                    "Read-only FoxESS command entity observed"
                    if available and value is not None
                    else "FoxESS command/readback entity has no usable read-only state"
                )
            ),
        }

    if ambiguous_keys:
        binding_status = "WAIT"
        binding_reason = (
            "Multiple command entities matched reviewed FoxESS keys: "
            + ", ".join(sorted(ambiguous_keys))
        )

    shadow = build_foxess_command_shadow(
        coordinator.data.control,
        observed,
        export_limit_kw=coordinator.settings.control.export_limit_kw,
    )
    shadow["entity_binding"] = {
        "status": binding_status,
        "reason": binding_reason,
        "telemetry_device_ids": list(telemetry_devices),
        "selected_device_id": selected_device,
        "entities": entity_bindings,
    }

    # Binding ambiguity is a stronger fail-closed condition than field parity.
    if binding_status != "PASS":
        shadow["parity_result"] = "WAIT"
        shadow["parity_reason"] = binding_reason

    return shadow
