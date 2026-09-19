"""Bounded Alpha9.62 FoxESS control backend.

The live KEMS FoxESS backend supports only:
- local Self Use ownership,
- confirmed-cheap-period Force Charge,
- Min SoC-on-grid enforcement,
- a sub-100 W closed-loop Force Discharge exception for grid-import prevention,
- fail-safe release back to the pre-KEMS local mode.

Deliberate/economic export, Agile/paid-export control and Export Power Limit
writes remain blocked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .const import DOMAIN, STORAGE_NAMESPACE
from .foxess_command_shadow import build_foxess_command_shadow_snapshot
from .foxess_modbus_contract import FOXESS_MODBUS_REVIEWED_VERSION
from .kems_core.control_write_authority import (
    FoxESSControlDecision,
    assess_foxess_control_write_authority,
)
from .kems_core.grid_bias_closed_loop import (
    GRID_BIAS_MAX_COMMAND_KW,
    next_grid_bias_control_step,
)

_STORAGE_VERSION = 1
_LOCAL_WORK_MODES = {"Self Use", "Feed-in First", "Back-up"}
_REMOTE_WORK_MODES = {"Force Charge", "Force Discharge"}
_KW_UNITS = {"kw", "kilowatt", "kilowatts"}
_REVIEWED_GRID_BIAS_STEP_KW = 0.001


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FoxESSControlBackend:
    """Own only the reviewed bounded non-Agile FoxESS command surface."""

    def __init__(self, hass: Any, entry: Any) -> None:
        self._hass = hass
        self._entry = entry
        self._store = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.{STORAGE_NAMESPACE}.foxess_control",
        )
        self._owned = False
        self._previous_work_mode: str | None = None
        self._previous_min_soc_on_grid: float | None = None
        self._grid_bias_force_discharge_kw = 0.0
        self._last_write_at: str | None = None
        self._last_write_result = "Never commanded"
        self._status: dict[str, Any] = {}

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        self._owned = bool(data.get("owned"))
        previous_mode = data.get("previous_work_mode")
        self._previous_work_mode = (
            str(previous_mode) if previous_mode in _LOCAL_WORK_MODES else None
        )
        self._previous_min_soc_on_grid = _number(data.get("previous_min_soc_on_grid"))
        stored_bias = _number(data.get("grid_bias_force_discharge_kw"))
        self._grid_bias_force_discharge_kw = (
            min(max(float(stored_bias or 0.0), 0.0), GRID_BIAS_MAX_COMMAND_KW)
            if self._owned
            else 0.0
        )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "owned": self._owned,
                "previous_work_mode": self._previous_work_mode,
                "previous_min_soc_on_grid": self._previous_min_soc_on_grid,
                "grid_bias_force_discharge_kw": self._grid_bias_force_discharge_kw,
            }
        )

    async def _foxess_version(self) -> str | None:
        try:
            integration = await async_get_integration(self._hass, "foxess_modbus")
        except Exception:
            return None
        return str(getattr(integration, "version", "") or "") or None

    @staticmethod
    def _binding_entities(shadow: dict[str, Any]) -> dict[str, Any]:
        binding = shadow.get("entity_binding")
        if not isinstance(binding, dict):
            return {}
        entities = binding.get("entities")
        return dict(entities) if isinstance(entities, dict) else {}

    @staticmethod
    def _entity_id(
        entities: dict[str, Any],
        key: str,
    ) -> str | None:
        item = entities.get(key)
        if not isinstance(item, dict) or item.get("status") != "PASS":
            return None
        entity_id = item.get("entity_id")
        return str(entity_id) if entity_id else None

    def _grid_bias_entity_contract(self, entity_id: str | None) -> dict[str, Any]:
        """Verify the reviewed v1.15.0 1 W Force Discharge number surface."""
        if entity_id is None:
            return {
                "ready": False,
                "entity_id": None,
                "reason": "Force Discharge Power entity is not uniquely bound",
            }
        state = self._hass.states.get(entity_id)
        if state is None:
            return {
                "ready": False,
                "entity_id": entity_id,
                "reason": "Force Discharge Power entity state is unavailable",
            }

        minimum = _number(state.attributes.get("min"))
        maximum = _number(state.attributes.get("max"))
        step = _number(state.attributes.get("step"))
        unit = str(state.attributes.get("unit_of_measurement") or "").casefold().strip()
        ready = bool(
            minimum is not None
            and minimum <= 0.0
            and maximum is not None
            and maximum >= GRID_BIAS_MAX_COMMAND_KW
            and step is not None
            and 0.0 < step <= _REVIEWED_GRID_BIAS_STEP_KW + 1e-9
            and unit in _KW_UNITS
        )
        if ready:
            reason = (
                "Reviewed Force Discharge Power surface supports the Alpha9.62 "
                "1 W-resolution bounded grid-bias trial"
            )
        else:
            reason = (
                "Force Discharge Power runtime contract differs from reviewed "
                "foxess_modbus v1.15.0 precision/range"
            )
        return {
            "ready": ready,
            "entity_id": entity_id,
            "min_kw": minimum,
            "max_kw": maximum,
            "step_kw": step,
            "unit": unit or None,
            "reviewed_max_step_kw": _REVIEWED_GRID_BIAS_STEP_KW,
            "live_command_ceiling_kw": GRID_BIAS_MAX_COMMAND_KW,
            "reason": reason,
        }

    async def _async_select(
        self,
        entity_id: str,
        option: str,
        writes: list[str],
    ) -> bool:
        state = self._hass.states.get(entity_id)
        options = tuple(
            str(item)
            for item in ((state.attributes.get("options") if state else None) or ())
        )
        if option not in options:
            self._last_write_result = f"FoxESS option unavailable: {option}"
            return False
        if state is not None and str(state.state) == option:
            return True
        try:
            async with asyncio.timeout(15):
                await self._hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": entity_id, "option": option},
                    blocking=True,
                )
        except Exception as err:
            self._last_write_result = f"FoxESS select write failed: {err}"
            return False
        writes.append(f"{entity_id}={option}")
        self._last_write_at = datetime.now(UTC).isoformat()
        return True

    async def _async_number(
        self,
        entity_id: str,
        value: float,
        writes: list[str],
        *,
        tolerance: float = 0.0005,
    ) -> bool:
        state = self._hass.states.get(entity_id)
        current = _number(state.state if state is not None else None)
        if current is not None and abs(current - value) <= tolerance:
            return True
        if state is not None:
            minimum = _number(state.attributes.get("min"))
            maximum = _number(state.attributes.get("max"))
            if minimum is not None and value < minimum - tolerance:
                self._last_write_result = (
                    f"FoxESS number target {value} is below {entity_id} "
                    f"minimum {minimum}"
                )
                return False
            if maximum is not None and value > maximum + tolerance:
                self._last_write_result = (
                    f"FoxESS number target {value} exceeds {entity_id} "
                    f"maximum {maximum}"
                )
                return False
        try:
            async with asyncio.timeout(15):
                await self._hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                    blocking=True,
                )
        except Exception as err:
            self._last_write_result = f"FoxESS number write failed: {err}"
            return False
        writes.append(f"{entity_id}={value}")
        self._last_write_at = datetime.now(UTC).isoformat()
        return True

    async def _async_take_ownership(
        self,
        entities: dict[str, Any],
    ) -> tuple[bool, str]:
        if self._owned:
            return True, "KEMS already owns the reviewed FoxESS control surface"

        work = entities.get("work_mode") or {}
        min_soc = entities.get("min_soc_on_grid") or {}
        work_mode = work.get("normalised_observation")
        min_soc_value = _number(min_soc.get("normalised_observation"))

        if work_mode in _REMOTE_WORK_MODES:
            return (
                False,
                "FoxESS remote control is already active outside KEMS ownership",
            )
        if work_mode not in _LOCAL_WORK_MODES:
            return False, f"Cannot preserve pre-KEMS FoxESS work mode: {work_mode!r}"
        if min_soc_value is None:
            return False, "Cannot preserve pre-KEMS Min SoC-on-grid readback"

        self._previous_work_mode = str(work_mode)
        self._previous_min_soc_on_grid = min_soc_value
        self._grid_bias_force_discharge_kw = 0.0
        self._owned = True
        await self._async_save()
        return True, "KEMS ownership captured with restorable local settings"

    async def _async_restore(
        self,
        entities: dict[str, Any],
        writes: list[str],
    ) -> bool:
        if not self._owned:
            self._grid_bias_force_discharge_kw = 0.0
            return True
        work_mode_entity = self._entity_id(entities, "work_mode")
        min_soc_entity = self._entity_id(entities, "min_soc_on_grid")
        if work_mode_entity is None or min_soc_entity is None:
            self._last_write_result = (
                "Cannot restore KEMS-owned FoxESS state: reviewed entities unavailable"
            )
            return False

        target_mode = self._previous_work_mode or "Self Use"
        if target_mode not in _LOCAL_WORK_MODES:
            target_mode = "Self Use"

        mode_ok = await self._async_select(work_mode_entity, target_mode, writes)
        soc_ok = True
        if self._previous_min_soc_on_grid is not None:
            soc_ok = await self._async_number(
                min_soc_entity,
                self._previous_min_soc_on_grid,
                writes,
                tolerance=0.05,
            )
        if mode_ok and soc_ok:
            self._owned = False
            self._grid_bias_force_discharge_kw = 0.0
            self._last_write_result = "KEMS FoxESS ownership released safely"
            await self._async_save()
            return True
        return False

    async def async_shutdown(self, coordinator: Any) -> None:
        """Release any KEMS-owned FoxESS state before integration unload."""
        if not self._owned:
            self._grid_bias_force_discharge_kw = 0.0
            return
        writes: list[str] = []
        try:
            shadow = build_foxess_command_shadow_snapshot(
                self._hass,
                coordinator,
                control_override=coordinator.data.control,
            )
            entities = self._binding_entities(shadow)
            restored = await self._async_restore(entities, writes)
            self._status = {
                **self._status,
                "shutdown_release_attempted": True,
                "shutdown_release_restored": restored,
                "shutdown_release_writes": writes,
                "owned_by_kems": self._owned,
                "grid_bias_owned_setpoint_kw": self._grid_bias_force_discharge_kw,
                "last_write_result": self._last_write_result,
            }
        except Exception as err:
            self._last_write_result = f"FoxESS shutdown restore failed: {err}"
            self._status = {
                **self._status,
                "shutdown_release_attempted": True,
                "shutdown_release_restored": False,
                "shutdown_release_writes": writes,
                "owned_by_kems": self._owned,
                "grid_bias_owned_setpoint_kw": self._grid_bias_force_discharge_kw,
                "last_write_result": self._last_write_result,
                "upstream_watchdog_fallback": True,
            }

    async def async_update(
        self,
        *,
        coordinator: Any,
        control: Any,
        technical_ready: bool,
        no_paid_export_mode: bool,
        cheap_period_confirmed: bool,
    ) -> dict[str, Any]:
        """Apply at most the bounded Alpha9.62 command for this scan."""
        shadow = build_foxess_command_shadow_snapshot(
            self._hass,
            coordinator,
            control_override=control,
        )
        binding = shadow.get("entity_binding")
        binding_root = dict(binding) if isinstance(binding, dict) else {}
        entities = self._binding_entities(shadow)
        required_keys = (
            "work_mode",
            "force_charge_power",
            "force_discharge_power",
            "min_soc_on_grid",
        )
        binding_ready = bool(
            binding_root.get("status") == "PASS"
            and all(
                isinstance(entities.get(key), dict)
                and entities[key].get("status") == "PASS"
                for key in required_keys
            )
        )
        observed_version = await self._foxess_version()
        version_matches = observed_version == FOXESS_MODBUS_REVIEWED_VERSION

        discharge_power_entity = self._entity_id(entities, "force_discharge_power")
        grid_bias_contract = self._grid_bias_entity_contract(discharge_power_entity)
        grid_bias_step = next_grid_bias_control_step(
            control,
            self._grid_bias_force_discharge_kw,
        )
        grid_bias_live_setpoint = (
            grid_bias_step.requested_setpoint_kw
            if grid_bias_step.active and bool(grid_bias_contract.get("ready"))
            else None
        )

        decision = assess_foxess_control_write_authority(
            control,
            technical_ready=technical_ready,
            binding_ready=binding_ready,
            reviewed_version_matches=version_matches,
            no_paid_export_mode=no_paid_export_mode,
            cheap_period_confirmed=cheap_period_confirmed,
            user_commissioned=bool(coordinator.settings.control.commissioned),
            master_control_enabled=bool(coordinator.settings.control.control_enabled),
            emergency_stop=bool(coordinator.settings.control.emergency_stop),
            grid_bias_force_discharge_kw=grid_bias_live_setpoint,
        )

        writes: list[str] = []
        applied = False
        reason = decision.reason

        if (
            grid_bias_step.active
            and not bool(grid_bias_contract.get("ready"))
            and decision.action == "self_use"
        ):
            reason = str(grid_bias_contract.get("reason") or reason)

        if not decision.commands_permitted:
            if self._owned:
                applied = await self._async_restore(entities, writes)
                if not applied:
                    reason = f"{reason}; KEMS-owned state restore is pending"
            elif self._grid_bias_force_discharge_kw > 0.0:
                self._grid_bias_force_discharge_kw = 0.0
                await self._async_save()
        else:
            owned, ownership_reason = await self._async_take_ownership(entities)
            if not owned:
                decision = FoxESSControlDecision(
                    backend_available=decision.backend_available,
                    commands_permitted=False,
                    action="none",
                    reason=ownership_reason,
                    min_soc_on_grid_percent=decision.min_soc_on_grid_percent,
                    grid_bias_shadow_only=decision.grid_bias_shadow_only,
                )
                reason = ownership_reason
            else:
                work_mode_entity = self._entity_id(entities, "work_mode")
                charge_power_entity = self._entity_id(
                    entities,
                    "force_charge_power",
                )
                discharge_power_entity = self._entity_id(
                    entities,
                    "force_discharge_power",
                )
                min_soc_entity = self._entity_id(entities, "min_soc_on_grid")
                if (
                    work_mode_entity is None
                    or charge_power_entity is None
                    or discharge_power_entity is None
                    or min_soc_entity is None
                ):
                    reason = "Reviewed FoxESS write entities disappeared before write"
                    decision = FoxESSControlDecision(
                        backend_available=False,
                        commands_permitted=False,
                        action="none",
                        reason=reason,
                        grid_bias_shadow_only=decision.grid_bias_shadow_only,
                    )
                    await self._async_restore(entities, writes)
                else:
                    min_soc_ok = await self._async_number(
                        min_soc_entity,
                        float(decision.min_soc_on_grid_percent or 0.0),
                        writes,
                        tolerance=0.05,
                    )
                    action_ok = False
                    if min_soc_ok and decision.action == "self_use":
                        action_ok = await self._async_select(
                            work_mode_entity,
                            "Self Use",
                            writes,
                        )
                        if action_ok and self._grid_bias_force_discharge_kw > 0.0:
                            self._grid_bias_force_discharge_kw = 0.0
                            await self._async_save()
                    elif (
                        min_soc_ok
                        and decision.action == "force_charge"
                        and decision.force_charge_power_kw is not None
                    ):
                        power_ok = await self._async_number(
                            charge_power_entity,
                            float(decision.force_charge_power_kw),
                            writes,
                        )
                        if power_ok:
                            action_ok = await self._async_select(
                                work_mode_entity,
                                "Force Charge",
                                writes,
                            )
                        if action_ok and self._grid_bias_force_discharge_kw > 0.0:
                            self._grid_bias_force_discharge_kw = 0.0
                            await self._async_save()
                    elif (
                        min_soc_ok
                        and decision.action == "grid_bias"
                        and decision.force_discharge_power_kw is not None
                        and bool(grid_bias_contract.get("ready"))
                    ):
                        power_ok = await self._async_number(
                            discharge_power_entity,
                            float(decision.force_discharge_power_kw),
                            writes,
                        )
                        if power_ok:
                            action_ok = await self._async_select(
                                work_mode_entity,
                                "Force Discharge",
                                writes,
                            )
                        if action_ok:
                            self._grid_bias_force_discharge_kw = float(
                                decision.force_discharge_power_kw
                            )
                            await self._async_save()

                    applied = bool(min_soc_ok and action_ok)
                    if applied:
                        self._last_write_result = (
                            "Alpha9.62 bounded FoxESS command applied"
                            if writes
                            else "Alpha9.62 bounded FoxESS command already matched"
                        )
                    else:
                        decision = FoxESSControlDecision(
                            backend_available=decision.backend_available,
                            commands_permitted=False,
                            action="release",
                            reason=self._last_write_result,
                            grid_bias_shadow_only=decision.grid_bias_shadow_only,
                        )
                        reason = self._last_write_result
                        await self._async_restore(entities, writes)

        if not control.grid_import_prevention_bias_active:
            bias_status = "inactive"
        elif not bool(grid_bias_contract.get("ready")):
            bias_status = "shadow_only"
        elif decision.grid_bias_live:
            bias_status = "live_bounded"
        elif grid_bias_step.reason == "self_use_already_at_or_below_bias_target":
            bias_status = "live_target_satisfied"
        else:
            bias_status = "armed"

        payload = {
            "scope": "alpha9.62_non_agile_grid_bias_trial",
            "reviewed_foxess_modbus_version": FOXESS_MODBUS_REVIEWED_VERSION,
            "observed_foxess_modbus_version": observed_version,
            "reviewed_version_matches": version_matches,
            "binding_ready": binding_ready,
            "technical_commissioning_ready": technical_ready,
            "operating_mode": control.operating_mode,
            "master_control_enabled": bool(
                coordinator.settings.control.control_enabled
            ),
            "user_commissioned": bool(coordinator.settings.control.commissioned),
            "no_paid_export_mode": bool(no_paid_export_mode),
            "cheap_period_confirmed": bool(cheap_period_confirmed),
            "backend_available": bool(decision.backend_available),
            "commands_permitted": bool(decision.commands_permitted and applied),
            "decision_action": decision.action,
            "decision_reason": reason,
            "owned_by_kems": self._owned,
            "previous_work_mode": self._previous_work_mode,
            "previous_min_soc_on_grid": self._previous_min_soc_on_grid,
            "writes_this_cycle": writes,
            "last_write_at": self._last_write_at,
            "last_write_result": self._last_write_result,
            "grid_import_prevention_bias": bias_status,
            "grid_bias_controller": {
                **grid_bias_step.to_dict(),
                "entity_contract": grid_bias_contract,
                "owned_setpoint_kw": round(self._grid_bias_force_discharge_kw, 3),
                "live_authority": bool(decision.grid_bias_live),
            },
            "deliberate_force_discharge": "blocked_except_bounded_grid_bias",
            "paid_or_agile_export_control": "blocked",
            "export_power_limit_write": "never_written_by_alpha9.62",
            "safety_release": (
                "restore pre-KEMS local mode and Min SoC-on-grid when owned"
            ),
        }
        self._status = payload
        return dict(payload)
