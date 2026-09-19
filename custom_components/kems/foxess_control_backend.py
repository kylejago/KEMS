"""Bounded Alpha9.64 FoxESS control backend.

The first real KEMS FoxESS backend intentionally supports only:
- local Self Use ownership,
- confirmed-cheap-period Force Charge,
- Min SoC-on-grid enforcement,
- fail-safe release back to the pre-KEMS local mode.

Deliberate/economic export and Agile/paid-export control remain blocked. Alpha9.64
retains Force Discharge only as the bounded near-zero grid-import trim and adds a
small fast loop around an already-authorised command; Export Power Limit is never
written by this backend.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
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
from .kems_core.fast_grid_trim import (
    FAST_GRID_TRIM_POLL_SECONDS,
    calculate_fast_grid_trim,
)
from .providers.foxess import FoxESSProvider

_STORAGE_VERSION = 1
_LOCAL_WORK_MODES = {"Self Use", "Feed-in First", "Back-up"}
_REMOTE_WORK_MODES = {"Force Charge", "Force Discharge"}


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FoxESSControlBackend:
    """Own only the reviewed non-Agile FoxESS command surface."""

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
        self._last_write_at: str | None = None
        self._last_write_result = "Never commanded"
        self._grid_bias_engaged = False
        self._grid_bias_correction_kw = 0.0
        self._write_lock = asyncio.Lock()
        self._fast_trim_task: asyncio.Task[None] | None = None
        self._fast_trim_context: dict[str, Any] | None = None
        self._fast_trim_last_sample_fingerprint: tuple[Any, ...] | None = None
        self._fast_trim_status: dict[str, Any] = {
            "state": "idle",
            "scheduler_interval_seconds": FAST_GRID_TRIM_POLL_SECONDS,
            "fresh_sample_required": True,
            "writes_work_mode": False,
            "writes_export_power_limit": False,
        }
        self._status: dict[str, Any] = {}

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self._owned = bool(data.get("owned"))
            previous_mode = data.get("previous_work_mode")
            self._previous_work_mode = (
                str(previous_mode) if previous_mode in _LOCAL_WORK_MODES else None
            )
            self._previous_min_soc_on_grid = _number(
                data.get("previous_min_soc_on_grid")
            )
        self._ensure_fast_trim_task()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "owned": self._owned,
                "previous_work_mode": self._previous_work_mode,
                "previous_min_soc_on_grid": self._previous_min_soc_on_grid,
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
        self._owned = True
        await self._async_save()
        return True, "KEMS ownership captured with restorable local settings"

    async def _async_restore(
        self,
        entities: dict[str, Any],
        writes: list[str],
    ) -> bool:
        if not self._owned:
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
            self._grid_bias_engaged = False
            self._grid_bias_correction_kw = 0.0
            self._last_write_result = "KEMS FoxESS ownership released safely"
            await self._async_save()
            return True
        return False

    def _ensure_fast_trim_task(self) -> None:
        """Keep one lightweight fast-trim scheduler alive for this config entry."""
        if self._fast_trim_task is not None and not self._fast_trim_task.done():
            return
        self._fast_trim_task = self._hass.async_create_task(
            self._async_fast_grid_trim_loop(),
            "KEMS FoxESS fast grid trim",
        )

    def _publish_fast_trim_status(self, **values: Any) -> None:
        self._fast_trim_status = {
            **self._fast_trim_status,
            **values,
        }
        if self._status:
            self._status = {
                **self._status,
                "fast_grid_trim": dict(self._fast_trim_status),
            }

    def _disarm_fast_grid_trim(self, reason: str) -> None:
        self._fast_trim_context = None
        self._fast_trim_last_sample_fingerprint = None
        self._publish_fast_trim_status(
            state="idle",
            reason=reason,
            armed=False,
        )

    @staticmethod
    def _state_is_on(hass: Any, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        state = hass.states.get(entity_id)
        return bool(state is not None and str(state.state).lower() == "on")

    def _grid_sample_fingerprint(
        self,
        context: dict[str, Any],
    ) -> tuple[Any, ...] | None:
        import_state = self._hass.states.get(context.get("grid_import_entity"))
        export_state = self._hass.states.get(context.get("grid_export_entity"))
        if import_state is None or export_state is None:
            return None
        return (
            str(import_state.state),
            getattr(import_state, "last_updated", None),
            str(export_state.state),
            getattr(export_state, "last_updated", None),
        )

    def _arm_fast_grid_trim(
        self,
        *,
        coordinator: Any,
        entities: dict[str, Any],
        control: Any,
        force_discharge_entity: str,
        work_mode_entity: str,
    ) -> None:
        loop = asyncio.get_running_loop()
        planner_interval = max(float(coordinator.settings.scan_interval_seconds), 30.0)
        authority_seconds = planner_interval + 15.0
        self._fast_trim_context = {
            "coordinator": coordinator,
            "entities": entities,
            "force_discharge_entity": force_discharge_entity,
            "work_mode_entity": work_mode_entity,
            "grid_import_entity": coordinator.entities.grid_import_kw,
            "grid_export_entity": coordinator.entities.grid_export_kw,
            "battery_soc_entity": coordinator.entities.battery_soc,
            "off_peak_entity": coordinator.entities.off_peak,
            "intelligent_slot_entity": coordinator.entities.intelligent_slot,
            "planner_base_output_kw": float(control.total_kh7_ac_output_kw),
            "planner_discharge_kw": float(control.desired_total_discharge_power_kw),
            "target_grid_w": float(
                control.grid_import_prevention_target_grid_power_w
            ),
            "min_soc_percent": float(control.desired_min_soc_percent),
            "inverter_limit_kw": float(coordinator.settings.control.inverter_limit_kw),
            "max_discharge_kw": float(coordinator.settings.control.max_discharge_kw),
            "export_limit_kw": float(coordinator.settings.control.export_limit_kw),
            "expires_at_monotonic": loop.time() + authority_seconds,
        }
        # The main planner has already acted on its current sample. Do not apply
        # the same grid error a second time before FoxESS publishes new telemetry.
        self._fast_trim_last_sample_fingerprint = self._grid_sample_fingerprint(
            self._fast_trim_context
        )
        self._publish_fast_trim_status(
            state="armed",
            reason="main_planner_authorised_grid_bias",
            armed=True,
            authority_seconds=round(authority_seconds, 1),
            planner_base_output_kw=round(float(control.total_kh7_ac_output_kw), 3),
            target_grid_w=float(control.grid_import_prevention_target_grid_power_w),
            last_sample_action="main_planner_sample_baseline",
        )

    async def _async_fast_grid_trim_release(self, reason: str) -> None:
        context = self._fast_trim_context
        writes: list[str] = []
        restored = False
        if self._owned and context is not None:
            restored = await self._async_restore(context["entities"], writes)
        self._fast_trim_context = None
        self._fast_trim_last_sample_fingerprint = None
        self._publish_fast_trim_status(
            state="released",
            reason=reason,
            armed=False,
            release_restored=restored,
            release_writes=writes,
        )

    async def _async_fast_grid_trim_loop(self) -> None:
        """Run a tiny scheduler; act only once for each new grid telemetry sample."""
        try:
            while True:
                await asyncio.sleep(FAST_GRID_TRIM_POLL_SECONDS)
                try:
                    await self._async_fast_grid_trim_once()
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    self._publish_fast_trim_status(
                        state="error",
                        reason=f"fast_grid_trim_error: {err}",
                    )
        except asyncio.CancelledError:
            raise

    async def _async_fast_grid_trim_once(self) -> None:
        """Nudge an already-authorised Force Discharge target from fresh grid data."""
        async with self._write_lock:
            context = self._fast_trim_context
            if context is None:
                return
            coordinator = context["coordinator"]
            settings = coordinator.settings.control
            loop = asyncio.get_running_loop()

            if loop.time() > float(context["expires_at_monotonic"]):
                await self._async_fast_grid_trim_release(
                    "main_planner_authority_expired"
                )
                return
            if (
                not self._owned
                or not self._grid_bias_engaged
                or not settings.control_enabled
                or not settings.commissioned
                or settings.emergency_stop
                or settings.operating_mode != "control"
            ):
                await self._async_fast_grid_trim_release(
                    "live_control_gate_withdrawn"
                )
                return
            if self._state_is_on(self._hass, context.get("off_peak_entity")) or (
                self._state_is_on(
                    self._hass,
                    context.get("intelligent_slot_entity"),
                )
            ):
                await self._async_fast_grid_trim_release(
                    "cheap_or_intelligent_signal_detected"
                )
                return

            work_state = self._hass.states.get(context["work_mode_entity"])
            if work_state is None or str(work_state.state) != "Force Discharge":
                self._disarm_fast_grid_trim(
                    "force_discharge_mode_changed_outside_fast_loop"
                )
                return

            fingerprint = self._grid_sample_fingerprint(context)
            if fingerprint is None:
                self._publish_fast_trim_status(
                    state="waiting",
                    reason="grid_entities_unavailable",
                    last_sample_action="no_write",
                )
                return
            if fingerprint == self._fast_trim_last_sample_fingerprint:
                self._publish_fast_trim_status(
                    state="armed",
                    reason="duplicate_grid_sample",
                    last_sample_action="no_write",
                )
                return
            self._fast_trim_last_sample_fingerprint = fingerprint

            foxess = FoxESSProvider(
                self._hass,
                coordinator.entities,
                stale_data_seconds=30,
            ).get_state()
            if foxess.grid_import_kw is None or foxess.grid_export_kw is None:
                self._publish_fast_trim_status(
                    state="waiting",
                    reason="fresh_grid_telemetry_unavailable",
                    last_sample_action="no_write",
                )
                return

            battery_state = self._hass.states.get(context.get("battery_soc_entity"))
            battery_soc = _number(
                battery_state.state if battery_state is not None else None
            )
            if battery_soc is None:
                self._publish_fast_trim_status(
                    state="waiting",
                    reason="battery_soc_unavailable",
                    last_sample_action="no_write",
                )
                return
            if battery_soc <= float(context["min_soc_percent"]) + 1e-6:
                await self._async_fast_grid_trim_release(
                    "battery_at_or_below_live_reserve"
                )
                return

            force_discharge_entity = str(context["force_discharge_entity"])
            power_state = self._hass.states.get(force_discharge_entity)
            current_force_discharge_kw = _number(
                power_state.state if power_state is not None else None
            )
            if current_force_discharge_kw is None:
                self._publish_fast_trim_status(
                    state="waiting",
                    reason="force_discharge_readback_unavailable",
                    last_sample_action="no_write",
                )
                return

            observed_grid_w = round(
                (
                    max(float(foxess.grid_import_kw), 0.0)
                    - max(float(foxess.grid_export_kw), 0.0)
                )
                * 1000.0,
                1,
            )
            result = calculate_fast_grid_trim(
                current_force_discharge_kw=current_force_discharge_kw,
                observed_grid_w=observed_grid_w,
                target_grid_w=float(context["target_grid_w"]),
                planner_base_output_kw=float(context["planner_base_output_kw"]),
                inverter_limit_kw=float(context["inverter_limit_kw"]),
                max_discharge_kw=float(context["max_discharge_kw"]),
                planner_discharge_kw=float(context["planner_discharge_kw"]),
                export_limit_kw=float(context["export_limit_kw"]),
            )
            writes: list[str] = []
            write_ok = True
            if result.changed:
                write_ok = await self._async_number(
                    force_discharge_entity,
                    result.target_force_discharge_kw,
                    writes,
                    tolerance=0.0049,
                )
            if not write_ok:
                await self._async_fast_grid_trim_release(
                    "fast_force_discharge_write_failed"
                )
                return

            self._grid_bias_correction_kw = max(
                result.target_force_discharge_kw
                - float(context["planner_base_output_kw"]),
                0.0,
            )
            self._publish_fast_trim_status(
                state="active",
                reason=result.reason,
                armed=True,
                observed_grid_w=result.observed_grid_w,
                target_grid_w=result.target_grid_w,
                error_w=result.error_w,
                current_force_discharge_kw=result.current_force_discharge_kw,
                target_force_discharge_kw=result.target_force_discharge_kw,
                delta_kw=result.delta_kw,
                envelope_min_kw=result.envelope_min_kw,
                envelope_max_kw=result.envelope_max_kw,
                last_sample_action=("write" if writes else "no_write"),
                last_sample_writes=writes,
                last_sample_at=datetime.now(UTC).isoformat(),
            )

    async def async_shutdown(self, coordinator: Any) -> None:
        """Release any KEMS-owned FoxESS state before integration unload."""
        task = self._fast_trim_task
        self._fast_trim_task = None
        self._fast_trim_context = None
        self._fast_trim_last_sample_fingerprint = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if not self._owned:
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
        """Serialize the 60-second planner write with the Alpha9.64 fast loop."""
        self._ensure_fast_trim_task()
        async with self._write_lock:
            return await self._async_update_locked(
                coordinator=coordinator,
                control=control,
                technical_ready=technical_ready,
                no_paid_export_mode=no_paid_export_mode,
                cheap_period_confirmed=cheap_period_confirmed,
            )

    async def _async_update_locked(
        self,
        *,
        coordinator: Any,
        control: Any,
        technical_ready: bool,
        no_paid_export_mode: bool,
        cheap_period_confirmed: bool,
    ) -> dict[str, Any]:
        """Apply the authoritative Alpha9.64 command for this planner scan."""
        shadow = build_foxess_command_shadow_snapshot(
            self._hass,
            coordinator,
            control_override=control,
        )
        binding = shadow.get("entity_binding")
        binding_root = dict(binding) if isinstance(binding, dict) else {}
        entities = self._binding_entities(shadow)
        required_keys = ("work_mode", "force_charge_power", "min_soc_on_grid")
        binding_ready = bool(
            binding_root.get("status") == "PASS"
            and all(
                isinstance(entities.get(key), dict)
                and entities[key].get("status") == "PASS"
                for key in required_keys
            )
        )
        grid_bias_force_discharge_ready = bool(
            isinstance(entities.get("force_discharge_power"), dict)
            and entities["force_discharge_power"].get("status") == "PASS"
        )
        observed_version = await self._foxess_version()
        version_matches = observed_version == FOXESS_MODBUS_REVIEWED_VERSION

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
            grid_bias_force_discharge_ready=grid_bias_force_discharge_ready,
            grid_bias_engaged=self._grid_bias_engaged,
            grid_bias_previous_correction_kw=self._grid_bias_correction_kw,
            inverter_limit_kw=float(coordinator.settings.control.inverter_limit_kw),
            max_discharge_kw=float(coordinator.settings.control.max_discharge_kw),
            export_limit_kw=float(coordinator.settings.control.export_limit_kw),
        )

        writes: list[str] = []
        applied = False
        reason = decision.reason

        if not decision.commands_permitted:
            self._disarm_fast_grid_trim("main_planner_withdrew_authority")
            if self._owned:
                applied = await self._async_restore(entities, writes)
                if not applied:
                    reason = f"{reason}; KEMS-owned state restore is pending"
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
                min_soc_entity = self._entity_id(entities, "min_soc_on_grid")
                force_discharge_entity = self._entity_id(
                    entities,
                    "force_discharge_power",
                )
                if (
                    work_mode_entity is None
                    or charge_power_entity is None
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
                        if action_ok:
                            self._grid_bias_engaged = False
                            self._grid_bias_correction_kw = 0.0
                            self._disarm_fast_grid_trim(
                                "main_planner_selected_self_use"
                            )
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
                            if action_ok:
                                self._grid_bias_engaged = False
                                self._grid_bias_correction_kw = 0.0
                                self._disarm_fast_grid_trim(
                                    "main_planner_selected_force_charge"
                                )
                    elif (
                        min_soc_ok
                        and decision.action == "grid_bias_force_discharge"
                        and decision.force_discharge_power_kw is not None
                        and force_discharge_entity is not None
                    ):
                        power_ok = await self._async_number(
                            force_discharge_entity,
                            float(decision.force_discharge_power_kw),
                            writes,
                            tolerance=0.01,
                        )
                        if power_ok:
                            action_ok = await self._async_select(
                                work_mode_entity,
                                "Force Discharge",
                                writes,
                            )
                            if action_ok:
                                self._grid_bias_engaged = True
                                self._grid_bias_correction_kw = float(
                                    decision.grid_bias_applied_correction_kw
                                )
                                self._arm_fast_grid_trim(
                                    coordinator=coordinator,
                                    entities=entities,
                                    control=control,
                                    force_discharge_entity=force_discharge_entity,
                                    work_mode_entity=work_mode_entity,
                                )
                    applied = bool(min_soc_ok and action_ok)
                    if applied:
                        self._last_write_result = (
                            "Alpha9.64 bounded FoxESS command applied"
                            if writes
                            else "Alpha9.64 bounded FoxESS command already matched"
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

        payload = {
            "scope": "alpha9.64_fast_trim_trial",
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
            "grid_import_prevention_bias": (
                "live_engaged"
                if self._grid_bias_engaged
                else (
                    "shadow_only"
                    if decision.grid_bias_shadow_only
                    else (
                        "live_ready"
                        if control.grid_import_prevention_bias_active
                        else "inactive"
                    )
                )
            ),
            "grid_import_prevention_observed_w": (
                control.grid_import_prevention_observed_grid_power_w
            ),
            "grid_import_prevention_target_w": (
                control.grid_import_prevention_target_grid_power_w
            ),
            "grid_import_prevention_force_discharge_kw": (
                decision.force_discharge_power_kw
            ),
            "grid_import_prevention_error_w": decision.grid_bias_error_w,
            "grid_import_prevention_requested_correction_kw": (
                decision.grid_bias_requested_correction_kw
            ),
            "grid_import_prevention_applied_correction_kw": (
                decision.grid_bias_applied_correction_kw
            ),
            "grid_import_prevention_controller_correction_kw": round(
                self._grid_bias_correction_kw,
                3,
            ),
            "grid_import_prevention_max_step_kw": 0.05,
            "main_planner_interval_seconds": coordinator.settings.scan_interval_seconds,
            "fast_grid_trim": dict(self._fast_trim_status),
            "deliberate_force_discharge": "blocked_except_bounded_grid_bias_trim",
            "paid_or_agile_export_control": "blocked",
            "export_power_limit_write": "never_written_by_alpha9.64",
            "safety_release": (
                "restore pre-KEMS local mode and Min SoC-on-grid when owned"
            ),
        }
        self._status = payload
        return dict(payload)
