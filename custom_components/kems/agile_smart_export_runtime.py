"""Efficient Home Assistant runtime wrapper for Agile Smart Export."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .agile_smart_export import (
    LONDON,
    PUBLISHED_PERIODS,
    AgileRate,
    AgileSmartExportManager,
    _aggregate,
    _api_dt,
    _dedupe,
    _empty_period,
    _state,
)
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    Snapshot,
    SolarForecastState,
)
from .tariff import TariffSettings

ANALYSIS_REFRESH = timedelta(minutes=5)
RECENT_RATE_LOOKBACK = timedelta(days=2)
TWELVE_MONTH_DAYS = 365
BENCHMARK_PERIODS = (*PUBLISHED_PERIODS, "365_days")
AGILE_FLOW_UNAVAILABLE = (
    "H=-1,S=-1,GI=-1,GE=-1,SH=-1,SB=-1,SE=-1,GB=-1,BH=-1,BE=-1,SOC=-1"
)


class EfficientAgileSmartExportManager(AgileSmartExportManager):
    """Avoid replaying settled history on every normal KEMS coordinator scan."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int) -> None:
        super().__init__(hass, entry_id, history_days)
        self._last_analysis: datetime | None = None
        self._panel_config: SimulationConfig | None = None
        self._panel_today_records: list[Snapshot] = []
        self._panel_tomorrow_records: list[Snapshot] = []

    async def async_update(
        self,
        *,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        learned: LearnedState,
        forecast: SolarForecastState,
        forecast_plan: ForecastPlanState,
        tariff: TariffSettings,
    ) -> dict[str, Any]:
        """Refresh live prices, then replay at most once every five minutes."""
        await self._refresh(records, now)
        now_utc = now.astimezone(UTC)
        if (
            self._last_analysis is not None
            and now_utc - self._last_analysis < ANALYSIS_REFRESH
            and self._state
        ):
            return self.state

        self._last_analysis = now_utc
        local_now = now.astimezone(LONDON)
        today = local_now.date()
        historical_days = {
            item.timestamp.astimezone(LONDON).date()
            for item in records
            if item.timestamp.astimezone(LONDON).date() < today
        }
        needs_backfill = any(
            day.isoformat() not in self._daily for day in historical_days
        )
        if needs_backfill:
            replay_records = records
        else:
            # Yesterday carries each independent simulated SOC into today. Older
            # completed days are already persisted in the all-time ledger.
            cutoff = today - timedelta(days=1)
            replay_records = [
                item
                for item in records
                if item.timestamp.astimezone(LONDON).date() >= cutoff
            ]

        # Keep exactly the records used to render the current/tomorrow Agile
        # simulation available to _publish(). This lets the dashboard and the
        # managed panel share one routing result without changing the optimiser.
        self._panel_config = config
        self._panel_today_records = [
            item
            for item in replay_records
            if item.timestamp.astimezone(LONDON).date() == today
        ]
        self._panel_tomorrow_records = self._tomorrow_records(
            local_now,
            learned,
            forecast,
            forecast_plan,
            tariff,
        )

        return await super().async_update(
            records=replay_records,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )

    async def _fetch_rates(
        self,
        records: list[Snapshot],
        now: datetime,
    ) -> None:
        """Backfill only missing settled days, otherwise refresh recent prices."""
        if not self._rate_url or not self._product_code or not self._tariff_code:
            raise ValueError("Agile tariff discovery is incomplete")

        local_today = now.astimezone(LONDON).date()
        missing_days = sorted(
            {
                item.timestamp.astimezone(LONDON).date()
                for item in records
                if item.timestamp.astimezone(LONDON).date() < local_today
                and item.timestamp.astimezone(LONDON).date().isoformat()
                not in self._daily
            }
        )
        if missing_days:
            earliest = datetime.combine(
                missing_days[0],
                time.min,
                tzinfo=LONDON,
            ).astimezone(UTC)
        else:
            earliest = now - RECENT_RATE_LOOKBACK

        end = datetime.combine(
            local_today + timedelta(days=2),
            time.min,
            tzinfo=LONDON,
        ).astimezone(UTC)
        params: dict[str, Any] | None = {
            "period_from": _api_dt(earliest),
            "period_to": _api_dt(end),
            "page_size": 1500,
        }
        session = async_get_clientsession(self._hass)
        url: str | None = self._rate_url
        fetched: list[AgileRate] = []
        while url:
            async with session.get(url, params=params, timeout=30) as response:
                response.raise_for_status()
                data = await response.json()
            params = None
            for item in data.get("results", []):
                if isinstance(item, dict) and item.get("valid_to") is not None:
                    fetched.append(
                        AgileRate.from_dict(
                            {
                                "product_code": self._product_code,
                                "tariff_code": self._tariff_code,
                                "value_inc_vat": item["value_inc_vat"],
                                "valid_from": item["valid_from"],
                                "valid_to": item["valid_to"],
                            }
                        )
                    )
            url = str(data.get("next")) if data.get("next") else None

        retain_days = max(self._history_days + 2, 120)
        cutoff = now - timedelta(days=retain_days)
        self._rates = _dedupe(
            [item for item in self._rates if item.valid_to >= cutoff] + fetched
        )

    def _periods(
        self,
        daily: dict[str, dict[str, Any]],
        today: date,
    ) -> dict[str, Any]:
        """Add honest rolling-window coverage and a 365-day comparison."""
        periods = super()._periods(daily, today)
        periods["365_days"] = _aggregate(
            [
                value
                for day, value in daily.items()
                if today - timedelta(days=TWELVE_MONTH_DAYS - 1)
                <= date.fromisoformat(day)
                <= today
            ],
            "365_days",
            "Last 365 days",
        )

        expected_days = {
            "yesterday": 1,
            "7_days": 7,
            "30_days": 30,
            "365_days": TWELVE_MONTH_DAYS,
        }
        for key, expected in expected_days.items():
            period = periods.get(key)
            if not period:
                continue
            included = int(period.get("days_included") or 0)
            period["days_expected"] = expected
            period["coverage_percent"] = round(
                100 * min(included, expected) / expected,
                1,
            )
            period["complete_window"] = included >= expected

        all_time = periods.get("all_time")
        if all_time:
            included = int(all_time.get("days_included") or 0)
            all_time["days_expected"] = included
            all_time["coverage_percent"] = 100.0 if included else 0.0
            all_time["complete_window"] = bool(included)
        return periods

    def _publish(self, state: dict[str, Any]) -> None:
        """Publish coverage, tariff benchmark, solar routing, and panel flow."""
        if self._panel_config is not None:
            _enrich_slot_routing(
                state.get("today_slots"),
                self._panel_today_records,
                self._panel_config,
                self._simulation,
            )
            _enrich_slot_routing(
                state.get("tomorrow_slots"),
                self._panel_tomorrow_records,
                self._panel_config,
                self._simulation,
            )
        _annotate_solar_first_display(state)
        periods = state.get("periods", {})
        settled_days = sorted(
            day
            for day, value in self._daily.items()
            if isinstance(value, dict) and value.get("ready")
        )
        rolling = periods.get("365_days", {})
        rolling_days = int(rolling.get("days_included") or 0)
        history_coverage = {
            "settled_days": len(settled_days),
            "target_days": TWELVE_MONTH_DAYS,
            "twelve_month_ready": bool(rolling.get("complete_window")),
            "rolling_365_days_included": rolling_days,
            "rolling_365_coverage_percent": float(
                rolling.get("coverage_percent") or 0.0
            ),
            "earliest_settled_day": settled_days[0] if settled_days else None,
            "latest_settled_day": settled_days[-1] if settled_days else None,
            "note": (
                "KEMS only claims a 12-month comparison after 365 valid daily "
                "replays; missing history is never invented."
            ),
        }
        state["history_coverage"] = history_coverage
        super()._publish(state)

        flow_state, flow_attrs = _agile_flow_payload(state)
        self._set(
            "sensor.kems_agile_smart_export_flow_now",
            flow_state,
            {
                "friendly_name": "Agile Smart Export flow now",
                "mode": "simulation_only",
                "protocol": "KEMS panel flow v1",
                **flow_attrs,
            },
        )

        today = periods.get("today", _empty_period("today", "Today"))
        today_agile = today.get("agile_smart_export", {})
        self._set(
            "sensor.kems_agile_solar_to_home_today",
            _state(today_agile.get("solar_to_home_kwh")),
            {
                "friendly_name": "Agile Smart Export solar to home today",
                "unit_of_measurement": "kWh",
                "routing_rule": (
                    "Outside a confirmed cheap period, solar serves home demand "
                    "before battery discharge; only surplus solar is considered "
                    "for storage or export."
                ),
            },
        )

        self._set(
            "sensor.kems_agile_history_coverage",
            f"{rolling_days}/{TWELVE_MONTH_DAYS} days",
            {
                "friendly_name": "Agile Smart Export historical coverage",
                **history_coverage,
            },
        )

        for key in BENCHMARK_PERIODS:
            period = periods.get(key, _empty_period(key, key))
            agile = period.get("agile_smart_export", {})
            benchmark_attrs = {
                "period": period.get("label", key),
                "days_included": int(period.get("days_included") or 0),
                "days_expected": period.get("days_expected"),
                "coverage_percent": period.get("coverage_percent"),
                "complete_window": period.get("complete_window"),
                "comparison_boundary": "same Agile Smart Export dispatch",
                "fixed_export_rate_pence": 12.0,
            }
            self._set(
                f"sensor.kems_agile_vs_fixed_12p_gain_{key}",
                _state(agile.get("gain_vs_fixed_12p_same_dispatch_pence")),
                {
                    "friendly_name": (
                        f"Agile tariff gain vs fixed 12p {period.get('label', key)}"
                    ),
                    "unit_of_measurement": "p",
                    **benchmark_attrs,
                },
            )
            self._set(
                f"sensor.kems_fixed_12p_same_dispatch_income_{key}",
                _state(agile.get("fixed_12p_same_dispatch_income_pence")),
                {
                    "friendly_name": (
                        "Fixed 12p income on Agile dispatch "
                        f"{period.get('label', key)}"
                    ),
                    "unit_of_measurement": "p",
                    **benchmark_attrs,
                },
            )

        period = periods.get(
            "365_days",
            _empty_period("365_days", "Last 365 days"),
        )
        agile = period.get("agile_smart_export", {})
        full = period.get("full_kems_forecast", {})
        comparison = period.get("comparison", {})
        common = {
            "days_included": int(period.get("days_included") or 0),
            "days_expected": TWELVE_MONTH_DAYS,
            "coverage_percent": float(period.get("coverage_percent") or 0.0),
            "complete_window": bool(period.get("complete_window")),
        }
        for entity_id, value, name, attrs in (
            (
                "sensor.kems_agile_smart_export_cost_365_days",
                agile.get("economic_net_cost_pence"),
                "Agile Smart Export cost Last 365 days",
                agile,
            ),
            (
                "sensor.kems_full_kems_forecast_comparison_cost_365_days",
                full.get("economic_net_cost_pence"),
                "Full KEMS Forecast comparison cost Last 365 days",
                full,
            ),
            (
                "sensor.kems_agile_advantage_365_days",
                comparison.get("agile_advantage_pence"),
                "Agile advantage Last 365 days",
                comparison,
            ),
        ):
            self._set(
                entity_id,
                _state(value),
                {
                    "friendly_name": name,
                    "unit_of_measurement": "p",
                    **common,
                    **attrs,
                },
            )
        winner = comparison.get("winner") or "Unavailable"
        if not period.get("complete_window"):
            winner = f"Collecting {rolling_days}/{TWELVE_MONTH_DAYS} days"
        self._set(
            "sensor.kems_full_kems_forecast_vs_agile_winner_365_days",
            winner,
            {
                "friendly_name": (
                    "Full KEMS Forecast vs Agile Smart Export winner Last 365 days"
                ),
                **common,
                **comparison,
            },
        )

    async def async_shutdown(self) -> None:
        """Remove completion-only dashboard states when KEMS unloads."""
        await super().async_shutdown()
        for entity_id in _completion_published_ids():
            self._hass.states.async_remove(entity_id)


def _snapshot_load(snapshot: Snapshot) -> float | None:
    """Return the house-load value used by the Agile replay."""
    value = (
        snapshot.house_load_kw
        if snapshot.house_load_kw is not None
        else snapshot.grid_import_kw
    )
    return max(float(value), 0.0) if value is not None else None


def _enrich_slot_routing(
    slots_value: Any,
    records: list[Snapshot],
    config: SimulationConfig,
    simulation: Any,
) -> None:
    """Add solar-to-home and panel routing fields to Agile half-hour slots."""
    if not isinstance(slots_value, list) or not slots_value or len(records) < 2:
        return

    slots: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for item in slots_value:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(str(item["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(item["valid_to"])).astimezone(UTC)
        except (KeyError, ValueError):
            continue
        slots.append((start, end, item))
    slots.sort(key=lambda value: value[0])
    if not slots:
        return

    accum: dict[int, dict[str, float]] = {
        id(item): {
            "house": 0.0,
            "solar": 0.0,
            "solar_home": 0.0,
            "cheap_house_grid": 0.0,
            "covered": 0.0,
        }
        for _, _, item in slots
    }
    ordered_records = sorted(records, key=lambda value: value.timestamp)
    slot_index = 0
    for current, following in zip(ordered_records, ordered_records[1:], strict=False):
        timestamp = current.timestamp.astimezone(UTC)
        while slot_index < len(slots) and timestamp >= slots[slot_index][1]:
            slot_index += 1
        if slot_index >= len(slots):
            break
        start, end, slot = slots[slot_index]
        if timestamp < start or timestamp >= end:
            continue
        seconds = max((following.timestamp - current.timestamp).total_seconds(), 0.0)
        hours = min(seconds / 3600.0, 0.5)
        if hours <= 0:
            continue
        load = _snapshot_load(current)
        following_load = _snapshot_load(following)
        if (
            current.stale_fields
            or following.stale_fields
            or load is None
            or following_load is None
            or current.current_import_rate is None
        ):
            continue

        load_kwh = load * hours
        solar_kwh = simulation._simulated_solar_power(current, config) * hours
        inverter_kwh = max(config.inverter_limit_kw, 0.0) * hours
        solar_home = (
            0.0
            if current.cheap_period_confirmed
            else min(solar_kwh, load_kwh, inverter_kwh)
        )
        values = accum[id(slot)]
        values["house"] += load_kwh
        values["solar"] += solar_kwh
        values["solar_home"] += solar_home
        if current.cheap_period_confirmed:
            values["cheap_house_grid"] += load_kwh
        values["covered"] += 1.0

    for _, _, slot in slots:
        values = accum[id(slot)]
        if values["covered"] <= 0:
            slot.setdefault("house_load_kwh", None)
            slot.setdefault("solar_generation_kwh", None)
            slot.setdefault("solar_to_home_kwh", None)
            slot.setdefault("grid_to_battery_kwh", None)
            continue
        slot["house_load_kwh"] = round(values["house"], 3)
        slot["solar_generation_kwh"] = round(values["solar"], 3)
        slot["solar_to_home_kwh"] = round(values["solar_home"], 3)
        grid_import = slot.get("grid_import_kwh")
        if grid_import is None:
            slot["grid_to_battery_kwh"] = None
        else:
            grid_charge_input = max(
                float(grid_import) - values["cheap_house_grid"],
                0.0,
            )
            slot["grid_to_battery_kwh"] = round(
                grid_charge_input * max(config.charge_efficiency, 0.0),
                3,
            )


def _annotate_solar_first_display(state: dict[str, Any]) -> None:
    """Make solar-to-home priority explicit in slot and current-action display."""
    for key in ("today_slots", "tomorrow_slots"):
        slots = state.get(key)
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            try:
                solar_home = float(slot.get("solar_to_home_kwh") or 0.0)
            except (TypeError, ValueError):
                solar_home = 0.0
            if solar_home <= 0.0005:
                continue
            actions = list(slot.get("actions") or [])
            if "solar to home first" not in actions:
                actions.insert(0, "solar to home first")
            slot["actions"] = actions

    generated_at = state.get("generated_at")
    if not generated_at:
        return
    try:
        now = datetime.fromisoformat(str(generated_at)).astimezone(UTC)
    except ValueError:
        return
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, ValueError):
            continue
        if start <= now < end:
            state["current_action"] = ", ".join(slot.get("actions") or ["Hold"])
            break


def _agile_flow_payload(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the current Agile slot in the panel's compact flow protocol."""
    generated_at = state.get("generated_at")
    if not generated_at:
        return AGILE_FLOW_UNAVAILABLE, {"available": False}
    try:
        now = datetime.fromisoformat(str(generated_at)).astimezone(UTC)
    except ValueError:
        return AGILE_FLOW_UNAVAILABLE, {"available": False}

    current_slot: dict[str, Any] | None = None
    start: datetime | None = None
    end: datetime | None = None
    for item in state.get("today_slots", []):
        if not isinstance(item, dict):
            continue
        try:
            candidate_start = datetime.fromisoformat(
                str(item["valid_from"])
            ).astimezone(UTC)
            candidate_end = datetime.fromisoformat(str(item["valid_to"])).astimezone(
                UTC
            )
        except (KeyError, ValueError):
            continue
        if candidate_start <= now < candidate_end:
            current_slot = item
            start = candidate_start
            end = candidate_end
            break
    if current_slot is None or start is None or end is None:
        return AGILE_FLOW_UNAVAILABLE, {"available": False}

    hours = max((end - start).total_seconds() / 3600.0, 0.0)
    if hours <= 0:
        return AGILE_FLOW_UNAVAILABLE, {"available": False}

    required = (
        "house_load_kwh",
        "solar_generation_kwh",
        "grid_import_kwh",
        "grid_export_kwh",
        "solar_to_home_kwh",
        "solar_to_battery_kwh",
        "solar_export_kwh",
        "grid_to_battery_kwh",
        "battery_to_home_kwh",
        "battery_export_kwh",
        "ending_soc_percent",
    )
    if any(current_slot.get(name) is None for name in required):
        return AGILE_FLOW_UNAVAILABLE, {
            "available": False,
            "slot": current_slot.get("label"),
        }

    def power(name: str) -> float:
        return max(float(current_slot.get(name) or 0.0) / hours, 0.0)

    flow = (
        f"H={power('house_load_kwh'):.3f},"
        f"S={power('solar_generation_kwh'):.3f},"
        f"GI={power('grid_import_kwh'):.3f},"
        f"GE={power('grid_export_kwh'):.3f},"
        f"SH={power('solar_to_home_kwh'):.3f},"
        f"SB={power('solar_to_battery_kwh'):.3f},"
        f"SE={power('solar_export_kwh'):.3f},"
        f"GB={power('grid_to_battery_kwh'):.3f},"
        f"BH={power('battery_to_home_kwh'):.3f},"
        f"BE={power('battery_export_kwh'):.3f},"
        f"SOC={float(current_slot['ending_soc_percent']):.1f}"
    )
    return flow, {
        "available": True,
        "slot": current_slot.get("label"),
        "valid_from": current_slot.get("valid_from"),
        "valid_to": current_slot.get("valid_to"),
        "agile_rate_pence": current_slot.get("rate_pence"),
        "action": ", ".join(current_slot.get("actions") or ["Hold"]),
    }


def _completion_published_ids() -> tuple[str, ...]:
    ids = [
        "sensor.kems_agile_history_coverage",
        "sensor.kems_agile_solar_to_home_today",
        "sensor.kems_agile_smart_export_flow_now",
        "sensor.kems_agile_smart_export_cost_365_days",
        "sensor.kems_full_kems_forecast_comparison_cost_365_days",
        "sensor.kems_agile_advantage_365_days",
        "sensor.kems_full_kems_forecast_vs_agile_winner_365_days",
    ]
    for key in BENCHMARK_PERIODS:
        ids += [
            f"sensor.kems_agile_vs_fixed_12p_gain_{key}",
            f"sensor.kems_fixed_12p_same_dispatch_income_{key}",
        ]
    return tuple(ids)
