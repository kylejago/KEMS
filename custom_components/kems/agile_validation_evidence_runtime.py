"""Alpha 7.19 evidence gating, SOC trajectory, audit, and backfill proof."""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from . import agile_history_backfill as backfill_base
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_deadline_dispatch import _target_percent
from .agile_rolling_replan import _current_agile_soc
from .kems_core import ForecastPlanState, SimulationConfig
from .tariff import TariffSettings

_EVIDENCE_SENSOR = "sensor.kems_agile_comparison_evidence"
_SOURCE_MAP_SENSOR = "sensor.kems_agile_backfill_source_map"
_AUDIT_SENSOR = "sensor.kems_agile_decision_audit"
_TRAJECTORY_SENSOR = "sensor.kems_agile_soc_trajectory"
_DEADLINE_SOC_SENSOR = "sensor.kems_agile_projected_soc_at_deadline"
_OVERNIGHT_TARGET_SENSOR = "sensor.kems_agile_overnight_recharge_target"

_AGILE_ENTITY_IDS = (
    _EVIDENCE_SENSOR,
    _AUDIT_SENSOR,
    _TRAJECTORY_SENSOR,
    _DEADLINE_SOC_SENSOR,
    _OVERNIGHT_TARGET_SENSOR,
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gate_fixed_windows(periods: dict[str, Any]) -> None:
    """Never publish a winner for an incomplete fixed-duration window."""
    for key in ("7_days", "30_days", "365_days"):
        period = periods.get(key)
        if not isinstance(period, dict):
            continue
        expected = int(period.get("days_expected") or 0)
        included = int(period.get("days_included") or 0)
        if expected <= 0:
            continue
        complete = included >= expected
        period["authoritative"] = complete
        period["evidence_status"] = (
            f"Ready — {included}/{expected} days"
            if complete
            else f"Collecting {included}/{expected} days"
        )
        if complete:
            continue
        comparison = period.get("comparison", {})
        if isinstance(comparison, dict):
            period["partial_comparison"] = dict(comparison)
        period["comparison"] = {
            "agile_advantage_pence": None,
            "winner": f"Collecting {included}/{expected} days",
            "winner_margin_pence": None,
        }
        period["ready"] = False

    all_time = periods.get("all_time")
    if isinstance(all_time, dict):
        included = int(all_time.get("days_included") or 0)
        all_time["authoritative"] = included > 0
        all_time["evidence_status"] = (
            f"Ready — {included} tracked days" if included else "Collecting evidence"
        )


def _periods_with_evidence(original):
    def periods(self, daily, today):
        result = original(self, daily, today)
        _gate_fixed_windows(result)
        return result

    periods._kems_alpha719_evidence = True
    return periods


def _slot_reason_codes(slot: dict[str, Any]) -> list[str]:
    """Return stable reason codes for one human-readable Agile plan slot."""
    text = " ".join(
        str(item)
        for item in [
            *(slot.get("actions") or []),
            slot.get("rolling_action") or "",
        ]
    ).lower()
    codes: list[str] = []
    rules = (
        ("maximum discharge", "maximum_discharge"),
        ("deadline", "deadline_discharge"),
        ("rolling", "rolling_replan"),
        ("high agile", "high_price_export"),
        ("cheap charge", "cheap_charge"),
        ("solar to home", "solar_to_home"),
        ("store solar", "solar_storage"),
        ("export solar", "solar_export"),
        ("battery to home", "battery_to_home"),
        ("protected import", "protected_import"),
        ("hold", "hold"),
    )
    for needle, code in rules:
        if needle in text and code not in codes:
            codes.append(code)
    if slot.get("rolling_planned_battery_export_kwh") and "rolling_replan" not in codes:
        codes.append("rolling_replan")
    return codes or ["future_or_hold"]


def _decision_audit(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Expose exactly why the current and upcoming Agile slots were selected."""
    now_utc = now.astimezone(UTC)
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counts: dict[str, int] = {}
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        codes = _slot_reason_codes(slot)
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
        row = {
            "label": slot.get("label"),
            "valid_from": slot.get("valid_from"),
            "valid_to": slot.get("valid_to"),
            "rate_pence": slot.get("rate_pence"),
            "reason_codes": codes,
            "actions": list(slot.get("actions") or []),
            "rolling_action": slot.get("rolling_action"),
            "planned_battery_export_kwh": slot.get(
                "rolling_planned_battery_export_kwh"
            ),
            "battery_export_kwh": slot.get("battery_export_kwh"),
            "ending_soc_percent": slot.get("ending_soc_percent"),
        }
        rows.append(row)
        if start <= now_utc < end:
            current = row
    upcoming = [
        row
        for row in rows
        if datetime.fromisoformat(str(row["valid_to"])).astimezone(UTC) > now_utc
    ][:12]
    return {
        "current": current,
        "upcoming": upcoming,
        "today": rows,
        "reason_counts": counts,
        "generated_at": now.isoformat(),
    }


def _cheap_end(deadline: datetime, tariff: TariffSettings) -> datetime:
    local_deadline = deadline.astimezone(agile.LONDON)
    day = local_deadline.date()
    if tariff.offpeak_end <= tariff.offpeak_start:
        day += timedelta(days=1)
    return datetime.combine(day, tariff.offpeak_end, tzinfo=agile.LONDON).astimezone(
        UTC
    )


def _soc_trajectory(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
    forecast_plan: ForecastPlanState,
) -> dict[str, Any]:
    """Build a transparent receding-horizon battery SOC trajectory."""
    soc = _current_agile_soc(state)
    if soc is None:
        return {"available": False, "reason": "waiting for current simulated SOC"}

    now_utc = now.astimezone(UTC)
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    target_soc = _target_percent(config)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    points: list[dict[str, Any]] = []

    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict) or slot.get("ending_soc_percent") is None:
            continue
        try:
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if end <= now_utc:
            points.append(
                {
                    "timestamp": end.isoformat(),
                    "soc_percent": round(float(slot["ending_soc_percent"]), 1),
                    "source": "settled_or_elapsed_replay",
                    "action": ", ".join(slot.get("actions") or []),
                }
            )

    points.append(
        {
            "timestamp": now_utc.isoformat(),
            "soc_percent": round(soc, 1),
            "source": "current_simulated_soc",
            "action": state.get("current_action"),
        }
    )

    rolling = state.get("rolling_export_plan", {})
    rolling = rolling if isinstance(rolling, dict) else {}
    protected_house = max(
        _number(rolling.get("protected_house_energy_kwh")) or 0.0,
        0.0,
    )
    future_slots: list[tuple[dict[str, Any], datetime, datetime, float]] = []
    total_hours = 0.0
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, deadline)
        if overlap_end <= overlap_start:
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        future_slots.append((slot, overlap_start, overlap_end, hours))
        total_hours += hours

    battery_kwh = capacity * min(max(soc, 0.0), 100.0) / 100.0
    target_kwh = capacity * target_soc / 100.0
    for slot, _, end, hours in future_slots:
        house_ac = protected_house * hours / total_hours if total_hours > 0 else 0.0
        export_ac = max(
            _number(slot.get("rolling_planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        battery_kwh = max(
            battery_kwh - (house_ac + export_ac) / efficiency,
            target_kwh,
        )
        points.append(
            {
                "timestamp": end.isoformat(),
                "soc_percent": round(100 * battery_kwh / capacity, 1),
                "source": "rolling_replan_conservative",
                "planned_battery_export_kwh": round(export_ac, 3),
                "protected_house_energy_kwh": round(house_ac, 3),
                "action": slot.get("rolling_action") or "re-evaluate next scan",
            }
        )

    projected_deadline_soc = round(100 * battery_kwh / capacity, 1)
    if deadline > now_utc and (
        not points or points[-1]["timestamp"] != deadline.isoformat()
    ):
        points.append(
            {
                "timestamp": deadline.isoformat(),
                "soc_percent": projected_deadline_soc,
                "source": "cheap_window_deadline",
                "action": f"target {target_soc:.1f}% by cheap-window start",
            }
        )

    overnight_target = forecast_plan.maximum_overnight_soc_percent
    if overnight_target is None:
        overnight_target = 100.0
    overnight_target = min(
        max(float(overnight_target), config.battery_reserve_percent),
        100.0,
    )
    charge_end = _cheap_end(deadline, tariff)
    cursor = deadline
    charge_battery = battery_kwh
    charge_target_kwh = capacity * overnight_target / 100.0
    while cursor < charge_end and charge_battery < charge_target_kwh - 1e-6:
        next_point = min(cursor + timedelta(minutes=30), charge_end)
        hours = (next_point - cursor).total_seconds() / 3600.0
        stored = (
            max(config.max_charge_kw, 0.0) * hours * max(config.charge_efficiency, 0.01)
        )
        charge_battery = min(charge_battery + stored, charge_target_kwh, capacity)
        points.append(
            {
                "timestamp": next_point.isoformat(),
                "soc_percent": round(100 * charge_battery / capacity, 1),
                "source": "cheap_charge_projection",
                "action": "cheap-period recharge toward forecast overnight target",
            }
        )
        cursor = next_point

    tomorrow_start = charge_end
    for slot in state.get("tomorrow_slots", []):
        if not isinstance(slot, dict) or slot.get("ending_soc_percent") is None:
            continue
        try:
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if end <= tomorrow_start:
            continue
        points.append(
            {
                "timestamp": end.isoformat(),
                "soc_percent": round(float(slot["ending_soc_percent"]), 1),
                "source": "tomorrow_forecast_replay",
                "action": ", ".join(slot.get("actions") or ["forecast slot"]),
            }
        )

    points.sort(key=lambda item: item["timestamp"])
    return {
        "available": True,
        "basis": "receding_horizon_conservative",
        "note": (
            "Future solar is not pre-spent before it actually arrives. Protected "
            "house demand and rolling export allocations reduce SOC before 23:30; "
            "cheap recharge then targets the forecast overnight requirement."
        ),
        "current_soc_percent": round(soc, 1),
        "target_soc_percent": round(target_soc, 1),
        "deadline": deadline.isoformat(),
        "projected_deadline_soc_percent": projected_deadline_soc,
        "protected_house_energy_kwh": round(protected_house, 3),
        "overnight_target_soc_percent": round(overnight_target, 1),
        "projected_morning_soc_percent": round(100 * charge_battery / capacity, 1),
        "points": points[-110:],
        "generated_at": now.isoformat(),
    }


async def _hourly_direct_diagnostics(self, now: datetime) -> dict[str, Any]:
    """Use the same hourly resolution as the actual direct backfill path."""
    sources = self._source_entities()
    if not sources or not self._hass.services.has_service("recorder", "get_statistics"):
        return {
            key: self._source_descriptor(entity_id, [])
            for key, entity_id in sources.items()
        }
    start = datetime.combine(
        now.date() - timedelta(days=backfill_base.TARGET_DAYS),
        time.min,
        tzinfo=backfill_base.LONDON,
    ).astimezone(UTC)
    end = datetime.combine(
        now.date(),
        time.min,
        tzinfo=backfill_base.LONDON,
    ).astimezone(UTC)
    try:
        response = await self._hass.services.async_call(
            "recorder",
            "get_statistics",
            {
                "start_time": start,
                "end_time": end,
                "statistic_ids": sorted(set(sources.values())),
                "period": "hour",
                "types": ["mean", "state"],
            },
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, TypeError, ValueError) as err:
        return {
            "query_error": str(err),
            **{
                key: self._source_descriptor(entity_id, [])
                for key, entity_id in sources.items()
            },
        }
    statistics = response.get("statistics", {}) if isinstance(response, dict) else {}
    return {
        key: self._source_descriptor(
            entity_id,
            statistics.get(entity_id, []) if isinstance(statistics, dict) else [],
        )
        for key, entity_id in sources.items()
    }


def _publish_source_map(self, config: SimulationConfig) -> None:
    sources = self._source_entities()
    diagnostics = self._state.get("direct_source_diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}

    def usable(key: str) -> bool:
        item = diagnostics.get(key, {})
        return bool(isinstance(item, dict) and item.get("long_term_statistics"))

    house_direct = bool(sources.get("house_load_kw") and usable("house_load_kw"))
    derive_keys = (
        "solar_power_kw",
        "grid_import_kw",
        "grid_export_kw",
        "battery_power_kw",
    )
    house_derived = all(sources.get(key) and usable(key) for key in derive_keys)
    missing: list[str] = []
    if not house_direct and not house_derived:
        missing.append(
            "house_load_kw, or solar + grid import + grid export + battery power"
        )
    if config.proposal_solar_enabled and not (
        sources.get("solar_power_kw") and usable("solar_power_kw")
    ):
        missing.append("solar_power_kw for proposal-solar historical replay")

    logical = {
        key: {
            "entity_id": entity_id,
            **(
                diagnostics.get(key, {})
                if isinstance(diagnostics.get(key, {}), dict)
                else {}
            ),
        }
        for key, entity_id in sources.items()
    }
    energy_sources = self._state.get("energy_fallback_sources", {})
    energy_diagnostics = self._state.get("energy_source_diagnostics", {})
    attributes = {
        "friendly_name": "Agile historical source map and prerequisites",
        "query_resolution": "hourly",
        "logical_sources": logical,
        "house_direct_ready": house_direct,
        "house_derivation_ready": house_derived,
        "proposal_solar_required": bool(config.proposal_solar_enabled),
        "missing_prerequisites": missing,
        "direct_path_ready": not missing,
        "backfill_method": self._state.get("backfill_method"),
        "backfill_reason": self._state.get("energy_fallback_reason")
        or self._state.get("reason"),
        "energy_dashboard_sources": energy_sources,
        "energy_dashboard_diagnostics": energy_diagnostics,
    }
    self._hass.states.async_set(
        _SOURCE_MAP_SENSOR,
        "Ready" if not missing else "Missing prerequisites",
        attributes,
    )


def install_alpha719_validation_patch() -> None:
    """Install evidence gating, validation telemetry, and exact backfill proof."""
    periods_method = runtime.EfficientAgileSmartExportManager._periods
    if not getattr(periods_method, "_kems_alpha719_evidence", False):
        runtime.EfficientAgileSmartExportManager._periods = _periods_with_evidence(
            periods_method
        )

    update = runtime.EfficientAgileSmartExportManager.async_update
    if not getattr(update, "_kems_alpha719_validation", False):
        original_update = update

        async def update_with_alpha719(
            self,
            *,
            records,
            now,
            config,
            learned,
            forecast,
            forecast_plan,
            tariff,
        ):
            self._alpha719_now = now
            self._alpha719_config = config
            self._alpha719_tariff = tariff
            self._alpha719_forecast_plan = forecast_plan
            return await original_update(
                self,
                records=records,
                now=now,
                config=config,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=tariff,
            )

        update_with_alpha719._kems_alpha719_validation = True
        runtime.EfficientAgileSmartExportManager.async_update = update_with_alpha719

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha719_validation", False):
        original_publish = publish

        def publish_with_alpha719(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            periods = state.get("periods", {})
            periods = periods if isinstance(periods, dict) else {}
            evidence = {}
            for key in ("7_days", "30_days", "365_days", "all_time"):
                period = periods.get(key, {})
                if not isinstance(period, dict):
                    continue
                evidence[key] = {
                    "days_included": int(period.get("days_included") or 0),
                    "days_expected": period.get("days_expected"),
                    "coverage_percent": period.get("coverage_percent"),
                    "authoritative": bool(period.get("authoritative")),
                    "status": period.get("evidence_status"),
                    "partial_comparison": period.get("partial_comparison"),
                }
            summary = " · ".join(
                f"{key.replace('_days', 'd')}: {item.get('status', '—')}"
                for key, item in evidence.items()
                if key != "all_time"
            )
            self._set(
                _EVIDENCE_SENSOR,
                summary or "Collecting evidence",
                {
                    "friendly_name": "Agile comparison evidence readiness",
                    "windows": evidence,
                    "rule": "fixed-window winners require complete daily coverage",
                    "mode": "simulation_only",
                },
            )

            now = getattr(self, "_alpha719_now", None)
            config = getattr(self, "_alpha719_config", None)
            tariff = getattr(self, "_alpha719_tariff", None)
            forecast_plan = getattr(self, "_alpha719_forecast_plan", None)
            if (
                isinstance(now, datetime)
                and isinstance(config, SimulationConfig)
                and isinstance(tariff, TariffSettings)
                and isinstance(forecast_plan, ForecastPlanState)
            ):
                audit = _decision_audit(state, now)
                current = audit.get("current") or {}
                self._set(
                    _AUDIT_SENSOR,
                    ", ".join(current.get("reason_codes") or ["Waiting"]),
                    {
                        "friendly_name": "Agile decision audit",
                        "mode": "simulation_only",
                        **audit,
                    },
                )
                trajectory = _soc_trajectory(
                    self,
                    state,
                    now=now,
                    config=config,
                    tariff=tariff,
                    forecast_plan=forecast_plan,
                )
                current_soc = trajectory.get("current_soc_percent")
                self._set(
                    _TRAJECTORY_SENSOR,
                    agile._state(current_soc),
                    {
                        "friendly_name": "Agile planned SOC trajectory",
                        "unit_of_measurement": "%",
                        "mode": "simulation_only",
                        **trajectory,
                    },
                )
                self._set(
                    _DEADLINE_SOC_SENSOR,
                    agile._state(trajectory.get("projected_deadline_soc_percent")),
                    {
                        "friendly_name": "Agile projected SOC at cheap-window start",
                        "unit_of_measurement": "%",
                        "target_soc_percent": trajectory.get("target_soc_percent"),
                        "deadline": trajectory.get("deadline"),
                        "basis": trajectory.get("basis"),
                        "mode": "simulation_only",
                    },
                )
                self._set(
                    _OVERNIGHT_TARGET_SENSOR,
                    agile._state(trajectory.get("overnight_target_soc_percent")),
                    {
                        "friendly_name": "Agile overnight recharge target SOC",
                        "unit_of_measurement": "%",
                        "projected_morning_soc_percent": trajectory.get(
                            "projected_morning_soc_percent"
                        ),
                        "mode": "simulation_only",
                    },
                )

        publish_with_alpha719._kems_alpha719_validation = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_alpha719

    backfill_target = backfill_base.AgileHistoryBackfill
    diagnostics = getattr(backfill_target, "_async_direct_diagnostics", None)
    if diagnostics is not None and not getattr(
        diagnostics, "_kems_alpha719_hourly", False
    ):
        _hourly_direct_diagnostics._kems_alpha719_hourly = True
        backfill_target._async_direct_diagnostics = _hourly_direct_diagnostics

    refresh = backfill_target._async_refresh
    if not getattr(refresh, "_kems_alpha719_source_map", False):
        original_refresh = refresh

        async def refresh_with_source_map(
            self,
            *,
            native_records,
            now,
            tariff,
            config,
        ):
            await original_refresh(
                self,
                native_records=native_records,
                now=now,
                tariff=tariff,
                config=config,
            )
            _publish_source_map(self, config)

        refresh_with_source_map._kems_alpha719_source_map = True
        backfill_target._async_refresh = refresh_with_source_map

    shutdown = backfill_target.async_shutdown
    if not getattr(shutdown, "_kems_alpha719_source_map", False):
        original_shutdown = shutdown

        async def shutdown_with_source_map(self) -> None:
            await original_shutdown(self)
            self._hass.states.async_remove(_SOURCE_MAP_SENSOR)

        shutdown_with_source_map._kems_alpha719_source_map = True
        backfill_target.async_shutdown = shutdown_with_source_map

    agile_shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(agile_shutdown, "_kems_alpha719_validation", False):
        original_agile_shutdown = agile_shutdown

        async def shutdown_with_alpha719(self) -> None:
            await original_agile_shutdown(self)
            for entity_id in _AGILE_ENTITY_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_alpha719._kems_alpha719_validation = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = shutdown_with_alpha719
