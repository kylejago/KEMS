"""Manual, ROI-neutral physical export commissioning for Alpha9.83."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core import ControlConfig, ControlState, SimulationState

_STORAGE_VERSION = 1
_PROOF_TARGET_KW = 1.0
_STRESS_SECONDS = 60
_MIN_EXPORT_SOC_PERCENT = 15.0
_MIN_START_SOC_PERCENT = 20.0
_MAX_PROOF_SOLAR_KW = 0.5
_HISTORY_LIMIT = 10


def _number(value: object) -> float | None:
    """Return one finite float when possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _iso(value: datetime | None) -> str | None:
    """Return one timestamp in a stable serialisable form."""
    return value.astimezone(UTC).isoformat() if value is not None else None


def agile_export_target_kw(agile_state: dict[str, Any]) -> float | None:
    """Return the current deliberate battery-export target from Agile."""
    plan = agile_state.get("rolling_export_plan")
    if not isinstance(plan, dict) or not plan.get("available"):
        return None
    target = _number(plan.get("current_battery_export_target_kw"))
    return max(target, 0.0) if target is not None else None


class ExportCommissioningTestController:
    """Own one manually requested physical export commissioning session.

    The real export tariff remains No paid export.  The session temporarily
    grants only the reviewed Force Discharge/Export Power Limit authority:
    1 kW physical proof first, then at most 60 seconds following the already
    calculated Agile rolling export target.  Physical energy stays in history;
    export income remains zero and any later cheap-grid recharge cost created
    by the test is excluded from actual ROI value.
    """

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.export_commissioning_test",
        )
        self._active = False
        self._stage = "idle"
        self._restore_requested = False
        self._successful_completion_requested = False
        self._requested_at: datetime | None = None
        self._stress_started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._stop_reason: str | None = None
        self._latest_agile_target_kw: float | None = None
        self._command_target_kw = 0.0
        self._peak_grid_export_kw = 0.0
        self._exported_kwh = 0.0
        self._last_observation_at: datetime | None = None
        self._last_grid_export_kw: float | None = None
        self._recharge_debt_stored_kwh = 0.0
        self._roi_excluded_recharge_cost_pence_by_date: dict[str, float] = {}
        self._history: list[dict[str, Any]] = []

    @property
    def active(self) -> bool:
        """Return whether a test or its mandatory restore is still active."""
        return bool(self._active or self._restore_requested)

    @property
    def hardware_authority_active(self) -> bool:
        """Return whether the temporary deliberate-export authority is live."""
        return bool(
            self._active
            and not self._restore_requested
            and self._stage in {"proof", "agile_stress"}
        )

    @property
    def restore_requested(self) -> bool:
        """Return whether the backend must restore the captured FoxESS baseline."""
        return self._restore_requested

    @property
    def stress_seconds(self) -> int:
        return _STRESS_SECONDS

    @property
    def status(self) -> dict[str, Any]:
        """Return the complete non-secret commissioning/financial audit."""
        return {
            "active": self.active,
            "hardware_authority_active": self.hardware_authority_active,
            "stage": self._stage,
            "requested_at": _iso(self._requested_at),
            "stress_started_at": _iso(self._stress_started_at),
            "completed_at": _iso(self._completed_at),
            "stop_reason": self._stop_reason,
            "proof_target_kw": _PROOF_TARGET_KW,
            "stress_duration_seconds": _STRESS_SECONDS,
            "minimum_export_soc_percent": _MIN_EXPORT_SOC_PERCENT,
            "maximum_proof_solar_kw": _MAX_PROOF_SOLAR_KW,
            "latest_agile_target_kw": self._latest_agile_target_kw,
            "command_target_kw": round(self._command_target_kw, 3),
            "peak_measured_grid_export_kw": round(self._peak_grid_export_kw, 3),
            "measured_commissioning_export_kwh": round(self._exported_kwh, 5),
            "recharge_debt_stored_kwh": round(
                self._recharge_debt_stored_kwh,
                5,
            ),
            "roi_excluded_recharge_cost_pence_by_date": {
                day: round(value, 5)
                for day, value in sorted(
                    self._roi_excluded_recharge_cost_pence_by_date.items()
                )
            },
            "financial_scope": "commissioning",
            "export_income_policy": "zero_no_paid_export",
            "physical_energy_history": "retained",
            "actual_roi_policy": "exclude_test_recharge_cost",
            "simulated_roi_policy": "unchanged_counterfactual",
            "history": list(self._history),
        }

    async def async_load(self) -> None:
        """Restore financial exclusions and fail-safe any interrupted session."""
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        self._recharge_debt_stored_kwh = max(
            _number(data.get("recharge_debt_stored_kwh")) or 0.0,
            0.0,
        )
        raw_exclusions = data.get("roi_excluded_recharge_cost_pence_by_date")
        if isinstance(raw_exclusions, dict):
            self._roi_excluded_recharge_cost_pence_by_date = {
                str(day): max(_number(value) or 0.0, 0.0)
                for day, value in raw_exclusions.items()
            }
        raw_history = data.get("history")
        if isinstance(raw_history, list):
            self._history = [
                dict(item)
                for item in raw_history[-_HISTORY_LIMIT:]
                if isinstance(item, dict)
            ]

        if bool(data.get("active")):
            # Never resume Force Discharge after a restart.  The first normal
            # coordinator cycle requests the backend's verified restore path.
            self._active = True
            self._stage = "restoring"
            self._restore_requested = True
            self._stop_reason = "Interrupted by Home Assistant restart"
            self._requested_at = self._parse_time(data.get("requested_at"))
            self._exported_kwh = max(
                _number(data.get("measured_commissioning_export_kwh")) or 0.0,
                0.0,
            )
            self._peak_grid_export_kw = max(
                _number(data.get("peak_measured_grid_export_kw")) or 0.0,
                0.0,
            )

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    async def async_save(self) -> None:
        """Persist only the restart-safe session/debt/audit fields."""
        await self._store.async_save(
            {
                "active": self.active,
                "stage": self._stage,
                "requested_at": _iso(self._requested_at),
                "measured_commissioning_export_kwh": self._exported_kwh,
                "peak_measured_grid_export_kw": self._peak_grid_export_kw,
                "recharge_debt_stored_kwh": self._recharge_debt_stored_kwh,
                "roi_excluded_recharge_cost_pence_by_date": (
                    self._roi_excluded_recharge_cost_pence_by_date
                ),
                "history": self._history[-_HISTORY_LIMIT:],
            }
        )

    def _start_gate_reason(
        self,
        *,
        snapshot: Any,
        control: ControlState,
        agile_state: dict[str, Any],
        no_paid_export_mode: bool,
        technical_ready: bool,
        emergency_stop: bool,
        ev_hold_active: bool,
    ) -> str | None:
        """Return a fail-closed reason or None when a test may begin."""
        if not no_paid_export_mode:
            return (
                "Export commissioning requires the real tariff to remain No paid export"
            )
        if control.operating_mode != "control":
            return "KEMS Mode must be Control"
        if not control.control_enabled:
            return "Master control enable must be ON"
        if not control.commissioned:
            return "KEMS must be commissioned for control"
        if not technical_ready:
            return "Control-critical commissioning evidence is not ready"
        if emergency_stop:
            return "Emergency stop is latched"
        if not control.data_fresh or getattr(snapshot, "stale_fields", ()):
            return "Required physical telemetry is stale"
        if control.island_mode_active or not control.grid_available:
            return "Export commissioning is blocked while islanded/off-grid"
        if not control.plan_safe or control.preflight_passed != control.preflight_total:
            return "The current KEMS control/preflight plan is not safe"
        if bool(getattr(snapshot, "cheap_period_confirmed", False)):
            return "Export commissioning is blocked during a confirmed cheap period"
        if bool(getattr(snapshot, "saving_session_active", False)):
            return "Export commissioning is blocked during Power Down"
        if getattr(snapshot, "ev_charging", None) is not False:
            return "Ohme must be available and the EV must not be charging"
        if ev_hold_active:
            return "An EV battery hold is active or pending"
        soc = _number(getattr(snapshot, "battery_soc", None))
        if soc is None or soc < _MIN_START_SOC_PERCENT:
            return (
                f"Battery SOC must be at least {_MIN_START_SOC_PERCENT:.0f}% "
                "for export commissioning"
            )
        solar = _number(getattr(snapshot, "solar_power_kw", None))
        if solar is None or solar > _MAX_PROOF_SOLAR_KW:
            return (
                "The 1 kW direction proof requires fresh solar telemetry at or below "
                f"{_MAX_PROOF_SOLAR_KW:.1f} kW"
            )
        agile_target = agile_export_target_kw(agile_state)
        if agile_target is None or agile_target <= 0.01:
            return "The current Agile rolling plan has no positive export target"
        return None

    async def async_start(
        self,
        *,
        snapshot: Any,
        control: ControlState,
        agile_state: dict[str, Any],
        no_paid_export_mode: bool,
        technical_ready: bool,
        emergency_stop: bool,
        ev_hold_active: bool,
        now: datetime,
    ) -> tuple[bool, str]:
        """Start one explicit manual commissioning session."""
        if self.active:
            return False, "An export commissioning session or restore is already active"
        reason = self._start_gate_reason(
            snapshot=snapshot,
            control=control,
            agile_state=agile_state,
            no_paid_export_mode=no_paid_export_mode,
            technical_ready=technical_ready,
            emergency_stop=emergency_stop,
            ev_hold_active=ev_hold_active,
        )
        if reason is not None:
            return False, reason

        self._active = True
        self._stage = "proof"
        self._restore_requested = False
        self._successful_completion_requested = False
        self._requested_at = now
        self._stress_started_at = None
        self._completed_at = None
        self._stop_reason = None
        self._latest_agile_target_kw = agile_export_target_kw(agile_state)
        self._command_target_kw = _PROOF_TARGET_KW
        self._peak_grid_export_kw = 0.0
        self._exported_kwh = 0.0
        self._last_observation_at = getattr(snapshot, "timestamp", now)
        self._last_grid_export_kw = max(
            _number(getattr(snapshot, "grid_export_kw", None)) or 0.0,
            0.0,
        )
        await self.async_save()
        return True, "1 kW export commissioning proof requested"

    async def async_request_stop(
        self,
        reason: str,
        *,
        successful: bool = False,
    ) -> None:
        """Withdraw temporary authority and require verified backend restoration."""
        if not self.active:
            return
        self._active = True
        self._stage = "restoring"
        self._restore_requested = True
        self._successful_completion_requested = successful
        self._stop_reason = reason
        self._command_target_kw = 0.0
        await self.async_save()

    def _runtime_gate_reason(
        self,
        *,
        snapshot: Any,
        control: ControlState,
        no_paid_export_mode: bool,
        emergency_stop: bool,
        ev_hold_active: bool,
    ) -> str | None:
        """Return a reason that requires immediate fail-safe restoration."""
        if not no_paid_export_mode:
            return "Real export tariff changed during commissioning"
        if control.operating_mode != "control":
            return "KEMS left Control mode"
        if not control.control_enabled or not control.commissioned:
            return "KEMS control authority was withdrawn"
        if emergency_stop:
            return "Emergency stop was latched"
        if not control.data_fresh or getattr(snapshot, "stale_fields", ()):
            return "Required telemetry became stale"
        if control.island_mode_active or not control.grid_available:
            return "Grid/island state no longer permits export"
        if not control.plan_safe or control.preflight_passed != control.preflight_total:
            return "The control/preflight plan is no longer safe"
        if bool(getattr(snapshot, "cheap_period_confirmed", False)):
            return "A confirmed cheap period started"
        if bool(getattr(snapshot, "saving_session_active", False)):
            return "Power Down became active"
        if getattr(snapshot, "ev_charging", None) is not False:
            return "EV charging/Ohme state no longer permits commissioning"
        if ev_hold_active:
            return "An EV battery hold became active or pending"
        soc = _number(getattr(snapshot, "battery_soc", None))
        if soc is None or soc <= _MIN_EXPORT_SOC_PERCENT + 0.5:
            return "Battery SOC reached the commissioning export reserve"
        solar = _number(getattr(snapshot, "solar_power_kw", None))
        if solar is None or solar > _MAX_PROOF_SOLAR_KW:
            return "Solar rose above the low-solar commissioning envelope"
        return None

    async def async_control_override(
        self,
        *,
        control: ControlState,
        snapshot: Any,
        agile_state: dict[str, Any],
        config: ControlConfig,
        backend_status: dict[str, Any],
        no_paid_export_mode: bool,
        emergency_stop: bool,
        ev_hold_active: bool,
        now: datetime,
    ) -> tuple[ControlState, bool]:
        """Return commissioning-only control intent and whether stress just began."""
        if not self.hardware_authority_active:
            return control, False

        reason = self._runtime_gate_reason(
            snapshot=snapshot,
            control=control,
            no_paid_export_mode=no_paid_export_mode,
            emergency_stop=emergency_stop,
            ev_hold_active=ev_hold_active,
        )
        if reason is not None:
            await self.async_request_stop(reason)
            return control, False

        if bool(backend_status.get("paid_export_stage_blocked")):
            await self.async_request_stop(
                str(
                    backend_status.get("paid_export_stage_reason")
                    or "1 kW physical export proof was blocked"
                )
            )
            return control, False

        stress_started = False
        if self._stage == "proof" and bool(
            backend_status.get("paid_export_live_proven")
        ):
            self._stage = "agile_stress"
            self._stress_started_at = now
            stress_started = True

        if (
            self._stage == "agile_stress"
            and self._stress_started_at is not None
            and (now - self._stress_started_at).total_seconds() >= _STRESS_SECONDS
        ):
            await self.async_request_stop(
                "Completed 60 second Agile-following export stress test",
                successful=True,
            )
            return control, False

        target = _PROOF_TARGET_KW
        if self._stage == "agile_stress":
            agile_target = agile_export_target_kw(agile_state)
            if agile_target is None:
                await self.async_request_stop(
                    "Agile rolling export target became unavailable"
                )
                return control, False
            self._latest_agile_target_kw = agile_target
            target = agile_target

        house_battery = max(control.desired_battery_to_home_power_kw, 0.0)
        solar = max(_number(getattr(snapshot, "solar_power_kw", None)) or 0.0, 0.0)
        headroom = max(
            min(
                config.export_limit_kw,
                config.max_discharge_kw - house_battery,
                config.inverter_limit_kw - solar - house_battery,
            ),
            0.0,
        )
        target = min(max(target, 0.0), headroom)

        if self._stage == "proof" and target + 1e-6 < _PROOF_TARGET_KW:
            await self.async_request_stop(
                "Available inverter/discharge headroom cannot safely prove 1 kW export"
            )
            return control, False

        total_discharge = house_battery + target
        total_output = solar + total_discharge
        safe = bool(
            control.plan_safe
            and target <= config.export_limit_kw + 1e-6
            and total_discharge <= config.max_discharge_kw + 1e-6
            and total_output <= config.inverter_limit_kw + 1e-6
        )
        if not safe:
            await self.async_request_stop(
                "Commissioning export target failed the physical power envelope"
            )
            return control, False

        self._command_target_kw = target
        if stress_started:
            await self.async_save()

        return (
            replace(
                control,
                operating_reason=(
                    "export_commissioning_proof"
                    if self._stage == "proof"
                    else "export_commissioning_agile_stress"
                ),
                desired_work_mode="Feed-in First" if target > 0.01 else "Self Use",
                desired_battery_export_power_kw=round(target, 3),
                desired_total_discharge_power_kw=round(total_discharge, 3),
                desired_min_soc_percent=max(
                    _MIN_EXPORT_SOC_PERCENT,
                    config.normal_reserve_percent,
                ),
                desired_ev_charging_allowed=False,
                desired_grid_export_allowed=True,
                total_kh7_ac_output_kw=round(total_output, 3),
                kh7_output_headroom_kw=round(
                    max(config.inverter_limit_kw - total_output, 0.0),
                    3,
                ),
                plan_safe=True,
                blocked_reason=(
                    "Manual export commissioning only; real export tariff remains "
                    "No paid export and export income remains zero"
                ),
                next_action=(
                    "Prove 1 kW battery discharge and physical grid export"
                    if self._stage == "proof"
                    else "Follow the live Agile export target for at most 60 seconds"
                ),
            ),
            stress_started,
        )

    async def async_observe_snapshot(
        self,
        snapshot: Any,
        now: datetime,
        config: Any,
    ) -> None:
        """Integrate test export and exact later cheap-grid recharge exclusion."""
        timestamp = getattr(snapshot, "timestamp", now)
        changed = False
        if self.hardware_authority_active and self._last_observation_at is not None:
            seconds = max(
                min((timestamp - self._last_observation_at).total_seconds(), 90.0),
                0.0,
            )
            export_now = max(
                _number(getattr(snapshot, "grid_export_kw", None)) or 0.0,
                0.0,
            )
            export_previous = (
                export_now
                if self._last_grid_export_kw is None
                else self._last_grid_export_kw
            )
            added = (export_previous + export_now) / 2.0 * seconds / 3600.0
            if added > 0:
                self._exported_kwh += added
                changed = True
            if export_now > self._peak_grid_export_kw:
                self._peak_grid_export_kw = export_now
                changed = True
            self._last_grid_export_kw = export_now

        self._last_observation_at = timestamp

        if (
            not self.active
            and self._recharge_debt_stored_kwh > 1e-6
            and bool(getattr(snapshot, "cheap_period_confirmed", False))
        ):
            rate = _number(getattr(snapshot, "current_import_rate", None))
            battery_power = _number(getattr(snapshot, "battery_power_kw", None))
            grid_import = max(
                _number(getattr(snapshot, "grid_import_kw", None)) or 0.0,
                0.0,
            )
            if (
                rate is not None
                and battery_power is not None
                and grid_import > 0.1
                and self._last_observation_at is not None
            ):
                positive_is_discharge = bool(
                    getattr(config, "battery_power_positive_is_discharge", True)
                )
                battery_charge_kw = max(
                    -battery_power if positive_is_discharge else battery_power,
                    0.0,
                )
                # The normal scan-to-scan delta is used; the 90 s cap prevents
                # an HA outage from fabricating a large financial exclusion.
                prior = getattr(self, "_last_recharge_observation_at", None)
                if prior is not None and battery_charge_kw > 0.1:
                    seconds = max(
                        min((timestamp - prior).total_seconds(), 90.0),
                        0.0,
                    )
                    stored_charge = battery_charge_kw * seconds / 3600.0
                    repaid = min(stored_charge, self._recharge_debt_stored_kwh)
                    if repaid > 0:
                        self._recharge_debt_stored_kwh -= repaid
                        grid_input = repaid / max(
                            float(getattr(config, "charge_efficiency", 0.95)),
                            0.01,
                        )
                        excluded_cost = grid_input * rate
                        day = timestamp.date().isoformat()
                        self._roi_excluded_recharge_cost_pence_by_date[day] = (
                            self._roi_excluded_recharge_cost_pence_by_date.get(day, 0.0)
                            + excluded_cost
                        )
                        changed = True
                self._last_recharge_observation_at = timestamp
            else:
                self._last_recharge_observation_at = timestamp
        else:
            self._last_recharge_observation_at = timestamp

        if changed:
            await self.async_save()

    async def async_after_backend(
        self,
        backend_status: dict[str, Any],
        *,
        now: datetime,
        config: ControlConfig,
    ) -> bool:
        """Advance proof/stress state or finish after verified restoration.

        Returns True when the coordinator should immediately refresh because the
        1 kW proof just promoted the session to the Agile stress phase.
        """
        if self._restore_requested:
            if not bool(backend_status.get("owned_by_kems")):
                await self._async_finalize(now=now, config=config)
            return False

        if not self._active:
            return False

        if bool(backend_status.get("paid_export_stage_blocked")):
            await self.async_request_stop(
                str(
                    backend_status.get("paid_export_stage_reason")
                    or "Physical export proof blocked"
                )
            )
            return False

        if self._stage == "proof" and bool(
            backend_status.get("paid_export_live_proven")
        ):
            self._stage = "agile_stress"
            self._stress_started_at = now
            await self.async_save()
            return True
        return False

    async def _async_finalize(
        self,
        *,
        now: datetime,
        config: ControlConfig,
    ) -> None:
        """Close the test only after the backend reports ownership released."""
        discharged_stored = self._exported_kwh / max(
            float(getattr(config, "discharge_efficiency", 0.95)),
            0.01,
        )
        self._recharge_debt_stored_kwh += max(discharged_stored, 0.0)
        result = {
            "requested_at": _iso(self._requested_at),
            "completed_at": _iso(now),
            "completed_successfully": self._successful_completion_requested,
            "completion_reason": self._stop_reason,
            "measured_export_kwh": round(self._exported_kwh, 5),
            "peak_grid_export_kw": round(self._peak_grid_export_kw, 3),
            "agile_target_kw": self._latest_agile_target_kw,
            "roi_included": False,
            "export_income_pence": 0.0,
        }
        self._history = [*self._history[-(_HISTORY_LIMIT - 1) :], result]
        self._active = False
        self._restore_requested = False
        self._stage = (
            "completed" if self._successful_completion_requested else "aborted"
        )
        self._completed_at = now
        self._command_target_kw = 0.0
        self._last_grid_export_kw = None
        self._successful_completion_requested = False
        await self.async_save()

    def roi_adjusted_simulation(
        self,
        simulation: SimulationState,
        now: datetime,
    ) -> SimulationState:
        """Exclude only replacement-energy cost from actual ROI value.

        Measured import/export energy and actual import cost stay truthful.  With
        the real tariff still No paid export, actual export income is already
        zero.  The only financial side effect to neutralise is the later cost of
        restoring battery energy spent by this physical test.
        """
        excluded = self._roi_excluded_recharge_cost_pence_by_date.get(
            now.date().isoformat(),
            0.0,
        )
        if excluded <= 0:
            return simulation
        avoided = simulation.actual_avoided_import_value_pence
        system_value = simulation.actual_system_value_pence
        return replace(
            simulation,
            actual_avoided_import_value_pence=(
                None if avoided is None else round(avoided + excluded, 6)
            ),
            actual_system_value_pence=(
                None if system_value is None else round(system_value + excluded, 6)
            ),
        )

    async def async_shutdown(self) -> None:
        """Persist active state so restart can demand a backend restore."""
        await self.async_save()
