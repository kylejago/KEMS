"""Bounded FoxESS control backend with staged paid-export commissioning.

The proven no-paid-export Self Use / confirmed-cheap Force Charge / MinSOC path
is retained unchanged.  Alpha9.82 additionally permits explicitly selected paid
export through Force Discharge only after the KEMS export ceiling is written and
verified, with a 1 kW first-export stage proving physical battery/grid direction
before the optimiser may request the full bounded target.

Import Power Limit is never written.
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
    repair_contaminated_min_soc_baseline,
    resolve_live_min_soc_on_grid,
    should_freeze_owned_ev_hold,
)

_STORAGE_VERSION = 1
_PAID_EXPORT_STAGE_KW = 1.0
_PAID_EXPORT_PROOF_SAMPLES = 2
_PAID_EXPORT_FAILURE_SAMPLES = 3
_PAID_EXPORT_MAX_SOLAR_KW = 0.5
_PAID_EXPORT_MIN_GRID_EXPORT_KW = 0.2
_PAID_EXPORT_MIN_BATTERY_DISCHARGE_KW = 0.25
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
        self._previous_force_discharge_power_kw: float | None = None
        self._previous_export_power_limit_w: float | None = None
        self._paid_export_live_proven = False
        self._paid_export_stage_samples = 0
        self._paid_export_stage_failures = 0
        self._paid_export_stage_blocked = False
        self._paid_export_stage_reason: str | None = None
        self._last_applied_action: str | None = None
        self._last_verified_min_soc_on_grid: float | None = None
        self._last_verified_min_soc_at: str | None = None
        self._last_write_at: str | None = None
        self._last_write_result = "Never commanded"
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
            self._previous_force_discharge_power_kw = _number(
                data.get("previous_force_discharge_power_kw")
            )
            self._previous_export_power_limit_w = _number(
                data.get("previous_export_power_limit_w")
            )
            self._paid_export_live_proven = bool(
                data.get("paid_export_live_proven", False)
            )
            self._paid_export_stage_blocked = bool(
                data.get("paid_export_stage_blocked", False)
            )
            stage_reason = data.get("paid_export_stage_reason")
            self._paid_export_stage_reason = str(stage_reason) if stage_reason else None
            last_action = data.get("last_applied_action")
            self._last_applied_action = (
                str(last_action)
                if last_action in {"self_use", "force_charge", "force_discharge"}
                else None
            )
            self._last_verified_min_soc_on_grid = _number(
                data.get("last_verified_min_soc_on_grid")
            )
            verified_at = data.get("last_verified_min_soc_at")
            self._last_verified_min_soc_at = str(verified_at) if verified_at else None

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "owned": self._owned,
                "previous_work_mode": self._previous_work_mode,
                "previous_min_soc_on_grid": self._previous_min_soc_on_grid,
                "previous_force_discharge_power_kw": (
                    self._previous_force_discharge_power_kw
                ),
                "previous_export_power_limit_w": self._previous_export_power_limit_w,
                "paid_export_live_proven": self._paid_export_live_proven,
                "paid_export_stage_blocked": self._paid_export_stage_blocked,
                "paid_export_stage_reason": self._paid_export_stage_reason,
                "last_applied_action": self._last_applied_action,
                "last_verified_min_soc_on_grid": (self._last_verified_min_soc_on_grid),
                "last_verified_min_soc_at": self._last_verified_min_soc_at,
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

    @staticmethod
    def _observation_entity_id(
        entities: dict[str, Any],
        key: str,
    ) -> str | None:
        item = entities.get(key)
        if not isinstance(item, dict) or item.get("status") != "PASS":
            return None
        observed = item.get("readback_entity_id") or item.get("entity_id")
        return str(observed) if observed else None

    async def _async_wait_number(
        self,
        entities: dict[str, Any],
        key: str,
        expected: float,
        *,
        tolerance: float,
        attempts: int = 12,
    ) -> bool:
        entity_id = self._observation_entity_id(entities, key)
        if entity_id is None:
            return False
        for _ in range(attempts):
            state = self._hass.states.get(entity_id)
            value = _number(state.state if state is not None else None)
            if value is not None and abs(value - expected) <= tolerance:
                return True
            await asyncio.sleep(0.25)
        return False

    async def _async_wait_state(
        self,
        entity_id: str,
        expected: str,
        *,
        attempts: int = 12,
    ) -> bool:
        for _ in range(attempts):
            state = self._hass.states.get(entity_id)
            if state is not None and str(state.state) == expected:
                return True
            await asyncio.sleep(0.25)
        return False

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
        force_discharge = entities.get("force_discharge_power") or {}
        export_limit = entities.get("export_power_limit") or {}
        work_mode = work.get("normalised_observation")
        min_soc_value = _number(min_soc.get("normalised_observation"))
        force_discharge_value = _number(force_discharge.get("normalised_observation"))
        export_limit_value = _number(export_limit.get("normalised_observation"))

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
        self._previous_force_discharge_power_kw = force_discharge_value
        self._previous_export_power_limit_w = export_limit_value
        self._last_verified_min_soc_on_grid = None
        self._last_verified_min_soc_at = None
        self._owned = True
        await self._async_save()
        return True, "KEMS ownership captured with restorable local settings"

    async def _async_complete_paid_export_baseline(
        self,
        entities: dict[str, Any],
    ) -> tuple[bool, str]:
        """Capture paid-export settings for owners created before Alpha9.82."""
        if not self._owned:
            return False, "KEMS does not own FoxESS"
        if (
            self._previous_force_discharge_power_kw is not None
            and self._previous_export_power_limit_w is not None
        ):
            return True, "Paid-export restore baseline is already complete"

        work = entities.get("work_mode") or {}
        work_mode = work.get("normalised_observation")
        if work_mode in _REMOTE_WORK_MODES:
            return False, (
                "Cannot capture paid-export baseline while FoxESS remote control "
                f"is already active: {work_mode!r}"
            )
        force_discharge = entities.get("force_discharge_power") or {}
        export_limit = entities.get("export_power_limit") or {}
        force_value = _number(force_discharge.get("normalised_observation"))
        export_value = _number(export_limit.get("normalised_observation"))
        if force_value is None or export_value is None:
            return (
                False,
                "Paid-export Force Discharge/export-limit readback unavailable",
            )

        self._previous_force_discharge_power_kw = force_value
        self._previous_export_power_limit_w = export_value
        await self._async_save()
        return True, "Paid-export restore baseline captured"

    async def _async_restore_paid_export_settings(
        self,
        entities: dict[str, Any],
        writes: list[str],
    ) -> bool:
        """Restore settings changed only by the paid-export path."""
        ok = True
        force_entity = self._entity_id(entities, "force_discharge_power")
        export_entity = self._entity_id(entities, "export_power_limit")
        if self._previous_force_discharge_power_kw is not None:
            if force_entity is None:
                ok = False
            else:
                ok = bool(
                    await self._async_number(
                        force_entity,
                        self._previous_force_discharge_power_kw,
                        writes,
                        tolerance=0.05,
                    )
                    and await self._async_wait_number(
                        entities,
                        "force_discharge_power",
                        self._previous_force_discharge_power_kw,
                        tolerance=0.05,
                    )
                    and ok
                )
        if self._previous_export_power_limit_w is not None:
            if export_entity is None:
                ok = False
            else:
                ok = bool(
                    await self._async_number(
                        export_entity,
                        self._previous_export_power_limit_w,
                        writes,
                        tolerance=1.0,
                    )
                    and await self._async_wait_number(
                        entities,
                        "export_power_limit",
                        self._previous_export_power_limit_w,
                        tolerance=1.0,
                    )
                    and ok
                )
        return ok

    async def _async_observe_paid_export_stage(
        self,
        *,
        snapshot: Any,
        entities: dict[str, Any],
        config: Any,
    ) -> None:
        """Promote the 1 kW first-export stage only after physical direction proof."""
        if (
            self._paid_export_live_proven
            or self._paid_export_stage_blocked
            or self._last_applied_action != "force_discharge"
        ):
            return

        work = entities.get("work_mode") or {}
        mode = str(work.get("normalised_observation") or "")
        if mode != "Force Discharge":
            return

        stale = set(getattr(snapshot, "stale_fields", ()) or ())
        if {"battery_power_kw", "grid_export_kw", "solar_power_kw"} & stale:
            return
        solar = _number(getattr(snapshot, "solar_power_kw", None))
        battery = _number(getattr(snapshot, "battery_power_kw", None))
        grid_export = _number(getattr(snapshot, "grid_export_kw", None))
        export_limit = _number(
            (entities.get("export_power_limit") or {}).get("normalised_observation")
        )
        if None in (solar, battery, grid_export, export_limit):
            return
        if solar > _PAID_EXPORT_MAX_SOLAR_KW:
            return

        if not bool(getattr(config, "battery_power_positive_is_discharge", True)):
            battery = -battery

        expected_limit_w = float(getattr(config, "export_limit_kw", 0.0)) * 1000.0
        limit_verified = abs(export_limit - expected_limit_w) <= 1.0
        direction_verified = bool(
            battery >= _PAID_EXPORT_MIN_BATTERY_DISCHARGE_KW
            and grid_export >= _PAID_EXPORT_MIN_GRID_EXPORT_KW
        )
        if limit_verified and direction_verified:
            self._paid_export_stage_samples += 1
            self._paid_export_stage_failures = 0
            self._paid_export_stage_reason = (
                f"Physical paid-export proof sample "
                f"{self._paid_export_stage_samples}/{_PAID_EXPORT_PROOF_SAMPLES}"
            )
            if self._paid_export_stage_samples >= _PAID_EXPORT_PROOF_SAMPLES:
                self._paid_export_live_proven = True
                self._paid_export_stage_reason = (
                    "Physical battery-discharge and grid-export directions proven"
                )
                await self._async_save()
            return

        self._paid_export_stage_samples = 0
        self._paid_export_stage_failures += 1
        self._paid_export_stage_reason = (
            "Staged Force Discharge did not prove battery discharge + grid export "
            f"({self._paid_export_stage_failures}/{_PAID_EXPORT_FAILURE_SAMPLES})"
        )
        if self._paid_export_stage_failures >= _PAID_EXPORT_FAILURE_SAMPLES:
            self._paid_export_stage_blocked = True
            self._paid_export_stage_reason = (
                "Paid export blocked after repeated failed 1 kW physical proof"
            )
            await self._async_save()

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
        mode_state = self._hass.states.get(work_mode_entity)
        mode_verified = bool(
            mode_state is not None and str(mode_state.state) == target_mode
        )
        soc_verified = True
        if self._previous_min_soc_on_grid is not None:
            soc_state = self._hass.states.get(min_soc_entity)
            restored_soc = _number(soc_state.state if soc_state is not None else None)
            soc_verified = bool(
                restored_soc is not None
                and abs(restored_soc - self._previous_min_soc_on_grid) <= 0.05
            )

        paid_settings_ok = await self._async_restore_paid_export_settings(
            entities,
            writes,
        )
        if mode_ok and soc_ok and mode_verified and soc_verified and paid_settings_ok:
            self._owned = False
            self._last_applied_action = None
            self._last_verified_min_soc_on_grid = None
            self._last_verified_min_soc_at = None
            self._last_write_result = "KEMS FoxESS ownership released safely"
            await self._async_save()
            return True
        if mode_ok and soc_ok:
            self._last_write_result = (
                "FoxESS restore command accepted; awaiting verified work mode, "
                "MinSOC or paid-export setting readback"
            )
            await self._async_save()
        return False

    async def async_shutdown(self, coordinator: Any) -> None:
        """Release any KEMS-owned FoxESS state before integration unload."""
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
        snapshot: Any,
        technical_ready: bool,
        no_paid_export_mode: bool,
        cheap_period_confirmed: bool,
        ev_hold_floor_percent: float | None = None,
        ev_connected: bool | None = None,
        ev_hold_source_grace_active: bool = False,
        pending_intelligent_ev_hold_active: bool = False,
    ) -> dict[str, Any]:
        """Apply the authoritative bounded non-Agile command for this scan."""
        shadow = build_foxess_command_shadow_snapshot(
            self._hass,
            coordinator,
            control_override=control,
        )
        binding = shadow.get("entity_binding")
        binding_root = dict(binding) if isinstance(binding, dict) else {}
        entities = self._binding_entities(shadow)
        required_keys = ["work_mode", "force_charge_power", "min_soc_on_grid"]
        if not no_paid_export_mode:
            required_keys.extend(("force_discharge_power", "export_power_limit"))
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
        effective_export_limit_kw = _number(shadow.get("effective_export_limit_kw"))

        if no_paid_export_mode:
            reset_needed = bool(
                self._paid_export_stage_samples
                or self._paid_export_stage_failures
                or self._paid_export_stage_blocked
            )
            self._paid_export_stage_samples = 0
            self._paid_export_stage_failures = 0
            self._paid_export_stage_blocked = False
            self._paid_export_stage_reason = None
            if reset_needed:
                await self._async_save()
        else:
            await self._async_observe_paid_export_stage(
                snapshot=snapshot,
                entities=entities,
                config=coordinator.settings.control,
            )

        min_soc_item = entities.get("min_soc_on_grid")
        observed_min_soc = _number(
            min_soc_item.get("normalised_observation")
            if isinstance(min_soc_item, dict)
            else None
        )
        min_soc_entity_id = self._entity_id(entities, "min_soc_on_grid")
        min_soc_state = (
            self._hass.states.get(min_soc_entity_id) if min_soc_entity_id else None
        )
        minimum_min_soc_on_grid = _number(
            min_soc_state.attributes.get("min") if min_soc_state is not None else None
        )
        baseline_before_repair = self._previous_min_soc_on_grid
        baseline_repair_applied = False
        if (
            not cheap_period_confirmed
            and ev_hold_floor_percent is None
            and not ev_hold_source_grace_active
            and not pending_intelligent_ev_hold_active
            and no_paid_export_mode
            and control.operating_mode == "control"
            and bool(coordinator.settings.control.control_enabled)
            and bool(coordinator.settings.control.commissioned)
        ):
            repaired_baseline = repair_contaminated_min_soc_baseline(
                self._previous_min_soc_on_grid,
                observed_min_soc_on_grid=observed_min_soc,
                last_verified_min_soc_on_grid=self._last_verified_min_soc_on_grid,
                minimum_min_soc_on_grid=minimum_min_soc_on_grid,
                requested_noncheap_min_soc=control.desired_min_soc_percent,
            )
            if (
                repaired_baseline is not None
                and self._previous_min_soc_on_grid is not None
                and abs(repaired_baseline - self._previous_min_soc_on_grid) > 0.05
            ):
                self._previous_min_soc_on_grid = repaired_baseline
                self._last_verified_min_soc_on_grid = None
                self._last_verified_min_soc_at = None
                baseline_repair_applied = True
                await self._async_save()
        if (
            self._owned
            and self._last_applied_action == "self_use"
            and ev_hold_floor_percent is not None
            and observed_min_soc is not None
            and observed_min_soc + 0.05 >= float(ev_hold_floor_percent)
            and self._last_verified_min_soc_on_grid != observed_min_soc
        ):
            self._last_verified_min_soc_on_grid = observed_min_soc
            self._last_verified_min_soc_at = datetime.now(UTC).isoformat()
            await self._async_save()

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
            effective_export_limit_kw=effective_export_limit_kw,
        )

        if (
            not no_paid_export_mode
            and decision.action == "force_discharge"
            and self._paid_export_stage_blocked
        ):
            decision = FoxESSControlDecision(
                backend_available=decision.backend_available,
                commands_permitted=False,
                action="release",
                reason=self._paid_export_stage_reason
                or "Paid export physical proof is blocked",
                min_soc_on_grid_percent=decision.min_soc_on_grid_percent,
            )

        writes: list[str] = []
        applied = False
        reason = decision.reason
        frozen_ev_hold = False

        frozen_ev_hold = should_freeze_owned_ev_hold(
            owned_by_kems=self._owned,
            latched_min_soc_percent=ev_hold_floor_percent,
            last_applied_action=self._last_applied_action,
            observed_min_soc_on_grid_percent=observed_min_soc,
            last_verified_min_soc_on_grid_percent=(self._last_verified_min_soc_on_grid),
            cheap_period_confirmed=cheap_period_confirmed,
            source_uncertainty_grace_active=ev_hold_source_grace_active,
            no_paid_export_mode=no_paid_export_mode,
            ev_connected=ev_connected,
            operating_mode=control.operating_mode,
            master_control_enabled=bool(coordinator.settings.control.control_enabled),
            user_commissioned=bool(coordinator.settings.control.commissioned),
            emergency_stop=bool(coordinator.settings.control.emergency_stop),
            island_mode_active=bool(control.island_mode_active),
            grid_available=bool(control.grid_available),
            pending_intelligent_ev_hold_active=pending_intelligent_ev_hold_active,
        )
        hold_grace_unverified = bool(
            ev_hold_source_grace_active
            and ev_hold_floor_percent is not None
            and not frozen_ev_hold
            and self._owned
            and self._last_applied_action == "self_use"
            and no_paid_export_mode
            and ev_connected is not False
            and control.operating_mode == "control"
            and bool(coordinator.settings.control.control_enabled)
            and bool(coordinator.settings.control.commissioned)
            and not bool(coordinator.settings.control.emergency_stop)
            and not bool(control.island_mode_active)
            and bool(control.grid_available)
        )

        if frozen_ev_hold:
            self._last_write_result = (
                "Alpha9.75 transient readiness loss: preserving only a "
                "physically verified EV MinSOC hold without new writes"
            )
            reason = (
                f"{reason}; verified "
                + ("pending Intelligent " if pending_intelligent_ev_hold_active else "")
                + f"EV hold frozen at {float(ev_hold_floor_percent):.1f}% "
                "until telemetry recovers or release authority becomes explicit"
            )
        elif hold_grace_unverified:
            self._last_write_result = (
                "Alpha9.75 source uncertainty grace: EV hold is not physically "
                "verified, so KEMS is issuing no write and claiming no protection"
            )
            reason = (
                f"{reason}; source uncertainty grace retained without writes "
                "because the latched EV hold is not physically verified"
            )
        elif not decision.commands_permitted:
            if self._owned:
                applied = await self._async_restore(entities, writes)
                if not applied:
                    reason = f"{reason}; KEMS-owned state restore is pending"
        else:
            owned, ownership_reason = await self._async_take_ownership(entities)
            if owned and not no_paid_export_mode:
                owned, ownership_reason = (
                    await self._async_complete_paid_export_baseline(entities)
                )
            if not owned:
                decision = FoxESSControlDecision(
                    backend_available=decision.backend_available,
                    commands_permitted=False,
                    action="none",
                    reason=ownership_reason,
                    min_soc_on_grid_percent=decision.min_soc_on_grid_percent,
                )
                reason = ownership_reason
                if self._owned:
                    await self._async_restore(entities, writes)
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
                export_limit_entity = self._entity_id(
                    entities,
                    "export_power_limit",
                )
                paid_entities_missing = bool(
                    not no_paid_export_mode
                    and (force_discharge_entity is None or export_limit_entity is None)
                )
                if (
                    work_mode_entity is None
                    or charge_power_entity is None
                    or min_soc_entity is None
                    or paid_entities_missing
                ):
                    reason = "Reviewed FoxESS write entities disappeared before write"
                    decision = FoxESSControlDecision(
                        backend_available=False,
                        commands_permitted=False,
                        action="none",
                        reason=reason,
                    )
                    await self._async_restore(entities, writes)
                else:
                    effective_min_soc = resolve_live_min_soc_on_grid(
                        decision,
                        cheap_period_confirmed=cheap_period_confirmed,
                        previous_min_soc_on_grid=self._previous_min_soc_on_grid,
                        pending_intelligent_ev_hold_active=(
                            pending_intelligent_ev_hold_active
                        ),
                    )
                    if effective_min_soc is None:
                        self._last_write_result = (
                            "Cannot preserve pre-KEMS Min SoC-on-grid "
                            "outside cheap period"
                        )
                        min_soc_ok = False
                    else:
                        min_soc_ok = await self._async_number(
                            min_soc_entity,
                            effective_min_soc,
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
                    elif (
                        min_soc_ok
                        and decision.action == "force_discharge"
                        and decision.force_discharge_power_kw is not None
                        and decision.export_power_limit_kw is not None
                        and force_discharge_entity is not None
                        and export_limit_entity is not None
                    ):
                        requested_discharge = float(decision.force_discharge_power_kw)
                        if not self._paid_export_live_proven:
                            requested_discharge = min(
                                requested_discharge,
                                _PAID_EXPORT_STAGE_KW,
                            )
                        export_limit_w = float(decision.export_power_limit_kw) * 1000.0
                        export_limit_ok = await self._async_number(
                            export_limit_entity,
                            export_limit_w,
                            writes,
                            tolerance=1.0,
                        )
                        if export_limit_ok:
                            export_limit_ok = await self._async_wait_number(
                                entities,
                                "export_power_limit",
                                export_limit_w,
                                tolerance=1.0,
                            )
                        discharge_ok = False
                        if export_limit_ok:
                            discharge_ok = await self._async_number(
                                force_discharge_entity,
                                requested_discharge,
                                writes,
                                tolerance=0.05,
                            )
                        if discharge_ok:
                            discharge_ok = await self._async_wait_number(
                                entities,
                                "force_discharge_power",
                                requested_discharge,
                                tolerance=0.05,
                            )
                        if discharge_ok:
                            mode_ok = await self._async_select(
                                work_mode_entity,
                                "Force Discharge",
                                writes,
                            )
                            if mode_ok:
                                action_ok = await self._async_wait_state(
                                    work_mode_entity,
                                    "Force Discharge",
                                )
                        if action_ok and not self._paid_export_live_proven:
                            self._paid_export_stage_reason = (
                                "1.0 kW first-export stage applied; awaiting two "
                                "low-solar physical direction samples"
                            )
                    applied = bool(min_soc_ok and action_ok)
                    if (
                        applied
                        and no_paid_export_mode
                        and decision.action == "self_use"
                    ):
                        paid_restore_ok = (
                            await self._async_restore_paid_export_settings(
                                entities,
                                writes,
                            )
                        )
                        applied = bool(applied and paid_restore_ok)
                    if applied:
                        if self._last_applied_action != decision.action:
                            self._last_applied_action = decision.action
                            await self._async_save()
                        if (
                            decision.action == "self_use"
                            and ev_hold_floor_percent is not None
                        ):
                            current_state = self._hass.states.get(min_soc_entity)
                            current_min_soc = _number(
                                current_state.state
                                if current_state is not None
                                else None
                            )
                            if (
                                current_min_soc is not None
                                and current_min_soc + 0.05
                                >= float(ev_hold_floor_percent)
                            ):
                                self._last_verified_min_soc_on_grid = current_min_soc
                                self._last_verified_min_soc_at = datetime.now(
                                    UTC
                                ).isoformat()
                                await self._async_save()
                        if pending_intelligent_ev_hold_active:
                            self._last_write_result = (
                                "Alpha9.76 pending Intelligent EV MinSOC hold applied"
                                if writes
                                else (
                                    "Alpha9.76 pending Intelligent EV MinSOC hold "
                                    "already matched"
                                )
                            )
                        else:
                            self._last_write_result = (
                                (
                                    "Alpha9.82 bounded paid-export command applied"
                                    if decision.action == "force_discharge"
                                    else "Alpha9.67 bounded FoxESS command applied"
                                )
                                if writes
                                else (
                                    (
                                        "Alpha9.82 bounded paid-export command "
                                        "already matched"
                                    )
                                    if decision.action == "force_discharge"
                                    else (
                                        "Alpha9.67 bounded FoxESS command "
                                        "already matched"
                                    )
                                )
                            )
                    else:
                        decision = FoxESSControlDecision(
                            backend_available=decision.backend_available,
                            commands_permitted=False,
                            action="release",
                            reason=self._last_write_result,
                        )
                        reason = self._last_write_result
                        await self._async_restore(entities, writes)

        payload = {
            "scope": "alpha9.82_bounded_control_with_paid_export",
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
            "decision_action": (
                "freeze_ev_hold"
                if frozen_ev_hold
                else (
                    "hold_grace_unverified"
                    if hold_grace_unverified
                    else (
                        "pending_intelligent_ev_hold"
                        if pending_intelligent_ev_hold_active
                        and decision.action == "self_use"
                        else decision.action
                    )
                )
            ),
            "decision_reason": reason,
            "ev_hold_frozen_on_transient_loss": frozen_ev_hold,
            "ev_hold_source_grace_active": ev_hold_source_grace_active,
            "pending_intelligent_ev_hold_active": pending_intelligent_ev_hold_active,
            "ev_hold_grace_unverified": hold_grace_unverified,
            "latched_ev_hold_min_soc_percent": ev_hold_floor_percent,
            "observed_min_soc_on_grid": observed_min_soc,
            "last_verified_min_soc_on_grid": self._last_verified_min_soc_on_grid,
            "last_verified_min_soc_at": self._last_verified_min_soc_at,
            "owned_by_kems": self._owned,
            "previous_work_mode": self._previous_work_mode,
            "previous_min_soc_on_grid": self._previous_min_soc_on_grid,
            "baseline_repair_applied": baseline_repair_applied,
            "baseline_repair_from_min_soc_on_grid": (
                baseline_before_repair if baseline_repair_applied else None
            ),
            "baseline_repair_to_min_soc_on_grid": (
                self._previous_min_soc_on_grid if baseline_repair_applied else None
            ),
            "baseline_repair_number_minimum": minimum_min_soc_on_grid,
            "last_applied_action": self._last_applied_action,
            "effective_min_soc_on_grid": (
                float(ev_hold_floor_percent)
                if frozen_ev_hold and ev_hold_floor_percent is not None
                else (
                    resolve_live_min_soc_on_grid(
                        decision,
                        cheap_period_confirmed=cheap_period_confirmed,
                        previous_min_soc_on_grid=self._previous_min_soc_on_grid,
                        pending_intelligent_ev_hold_active=(
                            pending_intelligent_ev_hold_active
                        ),
                    )
                    if decision.commands_permitted
                    else None
                )
            ),
            "non_cheap_min_soc_policy": (
                "pending_intelligent_ev_hold_only"
                if pending_intelligent_ev_hold_active
                else "preserve_pre_kems_baseline"
            ),
            "writes_this_cycle": writes,
            "last_write_at": self._last_write_at,
            "last_write_result": self._last_write_result,
            "normal_non_cheap_mode": "Self Use",
            "deliberate_force_discharge": (
                "bounded_live_when_paid_export_selected"
                if not no_paid_export_mode
                else "blocked_by_no_paid_export"
            ),
            "paid_or_agile_export_control": (
                "bounded_live"
                if not no_paid_export_mode
                else "blocked_by_no_paid_export"
            ),
            "effective_export_limit_kw": effective_export_limit_kw,
            "paid_export_live_proven": self._paid_export_live_proven,
            "paid_export_stage_kw": _PAID_EXPORT_STAGE_KW,
            "paid_export_stage_samples": self._paid_export_stage_samples,
            "paid_export_stage_required_samples": _PAID_EXPORT_PROOF_SAMPLES,
            "paid_export_stage_failures": self._paid_export_stage_failures,
            "paid_export_stage_blocked": self._paid_export_stage_blocked,
            "paid_export_stage_reason": self._paid_export_stage_reason,
            "previous_force_discharge_power_kw": (
                self._previous_force_discharge_power_kw
            ),
            "previous_export_power_limit_w": self._previous_export_power_limit_w,
            "export_power_limit_write": (
                "bounded_to_effective_ceiling_when_paid_export_is_active"
                if not no_paid_export_mode
                else "restored_or_untouched"
            ),
            "import_power_limit_write": "never_written_by_alpha9.82",
            "safety_release": (
                "restore pre-KEMS local mode, Min SoC-on-grid, Force Discharge "
                "setpoint and Export Power Limit when owned; an already-applied "
                "confirmed-cheap Self Use EV hold is frozen without writes "
                "across transient telemetry/readiness loss"
            ),
        }
        self._status = payload
        return dict(payload)\n