"""Region L Agile Outgoing prices and Agile Smart Export shadow simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SimulationEngine,
    Snapshot,
    SolarForecastState,
)
from .tariff import TariffSettings

REGION = "L"
FIXED_EXPORT_PENCE = 12.0
BATTERY_WEAR_PENCE_PER_KWH = 2.0
LONDON = ZoneInfo("Europe/London")
PRODUCTS_URL = "https://api.octopus.energy/v1/products/"
RATE_REFRESH = timedelta(minutes=15)
PRODUCT_REFRESH = timedelta(hours=24)
MIN_COVERAGE = 0.75
STORE_VERSION = 1
PUBLISHED_PERIODS = (
    "today",
    "tomorrow",
    "yesterday",
    "7_days",
    "30_days",
    "all_time",
)


@dataclass(frozen=True, slots=True)
class AgileRate:
    """One published Region L Agile Outgoing half-hour price."""

    product_code: str
    tariff_code: str
    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible rate record."""
        return {
            "product_code": self.product_code,
            "tariff_code": self.tariff_code,
            "region": REGION,
            "value_inc_vat": self.value_inc_vat,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgileRate:
        """Restore one persisted rate record."""
        return cls(
            product_code=str(value["product_code"]),
            tariff_code=str(value["tariff_code"]),
            value_inc_vat=float(value["value_inc_vat"]),
            valid_from=_dt(value["valid_from"]),
            valid_to=_dt(value["valid_to"]),
        )


class AgileSmartExportManager:
    """Collect prices, run read-only optimisation, persist daily comparisons."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int) -> None:
        self._hass = hass
        self._history_days = max(history_days, 1)
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORE_VERSION,
            f"{DOMAIN}.{entry_id}.agile_smart_export",
        )
        self._simulation = SimulationEngine()
        self._rates: list[AgileRate] = []
        self._daily: dict[str, dict[str, Any]] = {}
        self._product_code: str | None = None
        self._tariff_code: str | None = None
        self._rate_url: str | None = None
        self._last_product_refresh: datetime | None = None
        self._last_attempt: datetime | None = None
        self._last_success: datetime | None = None
        self._last_error: str | None = None
        self._dirty = False
        self._state: dict[str, Any] = {}

    @property
    def state(self) -> dict[str, Any]:
        """Return the latest dashboard/diagnostic payload."""
        return dict(self._state)

    async def async_load(self) -> None:
        """Restore persisted rate history and completed daily comparisons."""
        data = await self._store.async_load() or {}
        self._product_code = _text(data.get("product_code"))
        self._tariff_code = _text(data.get("tariff_code"))
        self._rate_url = _text(data.get("rate_url"))
        self._last_product_refresh = _maybe_dt(data.get("last_product_refresh"))
        self._last_success = _maybe_dt(data.get("last_success"))
        rates: list[AgileRate] = []
        for item in data.get("rates", []):
            if isinstance(item, dict):
                try:
                    rates.append(AgileRate.from_dict(item))
                except (KeyError, TypeError, ValueError):
                    pass
        self._rates = _dedupe(rates)
        if isinstance(data.get("daily"), dict):
            self._daily = {
                str(key): value
                for key, value in data["daily"].items()
                if isinstance(value, dict)
            }

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
        """Refresh prices and calculate every requested comparison period."""
        await self._refresh(records, now)
        local_now = now.astimezone(LONDON)
        grouped: dict[date, list[Snapshot]] = {}
        for item in sorted(records, key=lambda value: value.timestamp):
            grouped.setdefault(item.timestamp.astimezone(LONDON).date(), []).append(
                item
            )

        agile_soc = full_soc = max(
            config.battery_initial_percent,
            config.battery_reserve_percent,
        )
        calculated: dict[str, dict[str, Any]] = {}
        for day, day_records in sorted(grouped.items()):
            if len(day_records) < 2:
                continue
            result = self._compare_day(
                day_records,
                config,
                tariff,
                agile_soc,
                full_soc,
                (
                    learned.predicted_energy_until_offpeak_kwh
                    if day == local_now.date()
                    else None
                ),
            )
            calculated[day.isoformat()] = result
            agile_soc = float(
                result["agile_smart_export"].get("ending_soc_percent") or agile_soc
            )
            full_soc = float(
                result["full_kems_forecast"].get("ending_soc_percent") or full_soc
            )
            if day < local_now.date() and result["ready"]:
                compact = {
                    key: value for key, value in result.items() if key != "slot_plan"
                }
                if self._daily.get(day.isoformat()) != compact:
                    self._daily[day.isoformat()] = compact
                    self._dirty = True

        today = calculated.get(local_now.date().isoformat())
        tomorrow_records = self._tomorrow_records(
            local_now,
            learned,
            forecast,
            forecast_plan,
            tariff,
        )
        tomorrow = None
        if len(tomorrow_records) >= 2:
            tomorrow = self._compare_day(
                tomorrow_records,
                config,
                tariff,
                float(
                    (today or {})
                    .get("agile_smart_export", {})
                    .get("ending_soc_percent")
                    or agile_soc
                ),
                float(
                    (today or {})
                    .get("full_kems_forecast", {})
                    .get("ending_soc_percent")
                    or full_soc
                ),
                None,
                projection=True,
            )

        all_days = dict(self._daily)
        all_days.update(
            {
                key: {
                    name: value for name, value in result.items() if name != "slot_plan"
                }
                for key, result in calculated.items()
                if result["ready"]
            }
        )
        periods = self._periods(all_days, local_now.date())
        periods["today"] = _aggregate(
            [today] if today else [],
            "today",
            "Today",
        )
        periods["tomorrow"] = _aggregate(
            [tomorrow] if tomorrow else [],
            "tomorrow",
            "Tomorrow forecast",
        )
        today_slots = self._slot_payload(local_now.date(), today)
        tomorrow_slots = self._slot_payload(
            local_now.date() + timedelta(days=1),
            tomorrow,
        )
        quality = _quality(local_now, today_slots, tomorrow_slots)
        current = _rate_at(self._rates, now)
        self._state = {
            "name": "Agile Smart Export",
            "mode": "simulation_only",
            "region": REGION,
            "product_code": self._product_code,
            "tariff_code": self._tariff_code,
            "current_rate_pence": current.value_inc_vat if current else None,
            "fixed_export_benchmark_pence": FIXED_EXPORT_PENCE,
            "battery_wear_assumption_pence_per_discharged_kwh": (
                BATTERY_WEAR_PENCE_PER_KWH
            ),
            "current_action": _current_action(today_slots, now),
            "price_quality": quality,
            "today_slots": today_slots,
            "tomorrow_slots": tomorrow_slots,
            "periods": periods,
            "last_rate_success": (
                self._last_success.isoformat() if self._last_success else None
            ),
            "last_error": self._last_error,
            "generated_at": now.isoformat(),
            "ready": bool(today and today["ready"] and quality["today_complete"]),
        }
        self._publish(self._state)
        if self._dirty:
            await self.async_save()
        return self.state

    async def async_save(self) -> None:
        """Persist rate and all-time comparison history."""
        await self._store.async_save(
            {
                "product_code": self._product_code,
                "tariff_code": self._tariff_code,
                "rate_url": self._rate_url,
                "last_product_refresh": (
                    self._last_product_refresh.isoformat()
                    if self._last_product_refresh
                    else None
                ),
                "last_success": (
                    self._last_success.isoformat() if self._last_success else None
                ),
                "rates": [item.to_dict() for item in self._rates],
                "daily": self._daily,
            }
        )
        self._dirty = False

    async def async_shutdown(self) -> None:
        """Flush persistence and remove transient dashboard states on unload."""
        if self._dirty:
            await self.async_save()
        for entity_id in _published_ids():
            self._hass.states.async_remove(entity_id)

    async def _refresh(self, records: list[Snapshot], now: datetime) -> None:
        """Refresh live Octopus data no more than once per 15 minutes."""
        now_utc = now.astimezone(UTC)
        if self._last_attempt and now_utc - self._last_attempt < RATE_REFRESH:
            return
        self._last_attempt = now_utc
        try:
            if (
                not self._rate_url
                or not self._last_product_refresh
                or now_utc - self._last_product_refresh >= PRODUCT_REFRESH
            ):
                await self._discover(now_utc)
            await self._fetch_rates(records, now_utc)
        except (
            ClientError,
            TimeoutError,
            KeyError,
            TypeError,
            ValueError,
        ) as err:
            self._last_error = str(err)
            return
        self._last_success = now_utc
        self._last_error = None
        self._dirty = True

    async def _discover(self, now: datetime) -> None:
        """Discover the active Agile Outgoing product instead of hard-coding it."""
        session = async_get_clientsession(self._hass)
        products: list[dict[str, Any]] = []
        url: str | None = PRODUCTS_URL
        params: dict[str, Any] | None = {"page_size": 100}
        while url:
            async with session.get(url, params=params, timeout=20) as response:
                response.raise_for_status()
                data = await response.json()
            params = None
            products.extend(
                item for item in data.get("results", []) if isinstance(item, dict)
            )
            url = str(data.get("next")) if data.get("next") else None

        candidates = []
        for item in products:
            code = str(item.get("code", ""))
            name = str(item.get("display_name", ""))
            if str(item.get("direction", "")).upper() != "EXPORT":
                continue
            if "AGILE OUTGOING" not in name.upper() and not code.upper().startswith(
                "AGILE-OUTGOING"
            ):
                continue
            start = _maybe_dt(item.get("available_from"))
            end = _maybe_dt(item.get("available_to"))
            if (start and start > now) or (end and end <= now):
                continue
            candidates.append(item)
        if not candidates:
            raise ValueError("No active Octopus Agile Outgoing product was found")
        candidates.sort(
            key=lambda item: _maybe_dt(item.get("available_from"))
            or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        product_code = str(candidates[0]["code"])
        async with session.get(
            f"{PRODUCTS_URL}{product_code}/",
            timeout=20,
        ) as response:
            response.raise_for_status()
            detail = await response.json()

        region = detail.get("single_register_electricity_tariffs", {}).get(
            f"_{REGION}",
            {},
        )
        tariff = region.get("direct_debit_monthly")
        if not isinstance(tariff, dict):
            tariff = next(
                (value for value in region.values() if isinstance(value, dict)),
                None,
            )
        if not isinstance(tariff, dict):
            raise ValueError(f"Agile Outgoing does not expose Region {REGION}")
        rate_url = next(
            (
                str(link["href"])
                for link in tariff.get("links", [])
                if isinstance(link, dict)
                and link.get("rel") == "standard_unit_rates"
                and link.get("href")
            ),
            None,
        )
        if not tariff.get("code") or not rate_url:
            raise ValueError("Region L Agile Outgoing rate endpoint was not found")
        self._product_code = product_code
        self._tariff_code = str(tariff["code"])
        self._rate_url = rate_url
        self._last_product_refresh = now
        self._dirty = True

    async def _fetch_rates(
        self,
        records: list[Snapshot],
        now: datetime,
    ) -> None:
        """Backfill retained KEMS history and fetch all published tomorrow slots."""
        if not self._rate_url or not self._product_code or not self._tariff_code:
            raise ValueError("Agile tariff discovery is incomplete")
        retain = max(self._history_days + 2, 120)
        earliest = now - timedelta(days=retain)
        if records:
            earliest = min(
                earliest,
                min(item.timestamp.astimezone(UTC) for item in records),
            )
        end = datetime.combine(
            now.astimezone(LONDON).date() + timedelta(days=2),
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
                        AgileRate(
                            self._product_code,
                            self._tariff_code,
                            float(item["value_inc_vat"]),
                            _dt(item["valid_from"]),
                            _dt(item["valid_to"]),
                        )
                    )
            url = str(data.get("next")) if data.get("next") else None
        cutoff = now - timedelta(days=retain)
        self._rates = _dedupe(
            [item for item in self._rates if item.valid_to >= cutoff] + fetched
        )

    def _compare_day(
        self,
        records: list[Snapshot],
        config: SimulationConfig,
        tariff: TariffSettings,
        agile_soc: float,
        full_soc: float,
        learned_forecast: float | None,
        projection: bool = False,
    ) -> dict[str, Any]:
        """Replay one day through both strategies from independent battery SOCs."""
        records = sorted(records, key=lambda item: item.timestamp)
        day = records[0].timestamp.astimezone(LONDON).date()
        full_records = [replace(records[0], battery_soc=None), *records[1:]]
        full = self._simulation.simulate_today(
            full_records,
            full_records[-1].timestamp,
            replace(
                config,
                battery_initial_percent=full_soc,
                export_tariff_status="active",
                battery_export_enabled=True,
                strategy="paced_export",
                forecast_aware=True,
            ),
            learned_forecast,
            current_snapshot=full_records[-1],
        )
        standing = _standing(records)
        full_discharge = float(full.simulated_battery_to_home_kwh or 0) + float(
            full.simulated_battery_export_kwh or 0
        )
        full_wear = full_discharge * BATTERY_WEAR_PENCE_PER_KWH
        full_energy_cost = float(full.simulated_cost_pence or 0) + standing
        full_summary = {
            "ready": bool(full.ready),
            "energy_net_cost_pence": round(full_energy_cost, 2),
            "economic_net_cost_pence": round(
                full_energy_cost + full_wear,
                2,
            ),
            "import_cost_pence": round(
                float(full.simulated_import_cost_pence or 0),
                2,
            ),
            "export_income_pence": round(
                float(full.simulated_export_income_pence or 0),
                2,
            ),
            "grid_import_kwh": round(
                float(full.simulated_grid_import_kwh or 0),
                3,
            ),
            "grid_export_kwh": round(
                float(full.simulated_grid_export_kwh or 0),
                3,
            ),
            "solar_export_kwh": round(
                float(full.simulated_solar_export_kwh or 0),
                3,
            ),
            "solar_to_battery_kwh": round(
                float(full.simulated_solar_to_battery_kwh or 0),
                3,
            ),
            "battery_to_home_kwh": round(
                float(full.simulated_battery_to_home_kwh or 0),
                3,
            ),
            "battery_export_kwh": round(
                float(full.simulated_battery_export_kwh or 0),
                3,
            ),
            "battery_wear_cost_pence": round(full_wear, 2),
            "ending_soc_percent": full.simulated_battery_soc,
            "data_coverage": round(float(full.data_coverage), 4),
        }
        agile_summary, plan = self._agile_day(
            records,
            self._day_rates(day),
            config,
            tariff,
            agile_soc,
        )
        ready = bool(full_summary["ready"] and agile_summary["ready"])
        advantage = (
            float(full_summary["economic_net_cost_pence"])
            - float(agile_summary["economic_net_cost_pence"])
            if ready
            else None
        )
        return {
            "date": day.isoformat(),
            "projection": projection,
            "ready": ready,
            "full_kems_forecast": full_summary,
            "agile_smart_export": agile_summary,
            "comparison": _comparison(advantage),
            "slot_plan": plan,
        }

    def _agile_day(
        self,
        records: list[Snapshot],
        rates: list[AgileRate],
        config: SimulationConfig,
        tariff: TariffSettings,
        initial_soc: float,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Optimise export timing while never causing an avoidable day-rate import."""
        capacity = max(config.battery_capacity_kwh, 0.1)
        reserve = capacity * max(config.battery_reserve_percent, 0) / 100
        battery = min(
            max(capacity * initial_soc / 100, reserve),
            capacity,
        )
        totals = {
            key: 0.0
            for key in (
                "import_cost",
                "income",
                "fixed_income",
                "grid_import",
                "grid_export",
                "solar",
                "solar_home",
                "solar_battery",
                "solar_export",
                "grid_battery",
                "battery_home",
                "battery_export",
                "curtailed",
            )
        }
        intervals = covered = 0
        plans: dict[str, dict[str, Any]] = {}
        for index, (current, following) in enumerate(
            zip(records, records[1:], strict=False)
        ):
            hours = min(
                max(
                    (following.timestamp - current.timestamp).total_seconds(),
                    0,
                )
                / 3600,
                0.5,
            )
            if hours <= 0:
                continue
            intervals += 1
            slot = _rate_at(rates, current.timestamp)
            load = _load(current)
            if (
                current.stale_fields
                or following.stale_fields
                or slot is None
                or load is None
                or _load(following) is None
                or current.current_import_rate is None
            ):
                continue
            covered += 1
            rate = slot.value_inc_vat
            import_rate = float(current.current_import_rate)
            load_kwh = load * hours
            solar_kwh = self._simulation._simulated_solar_power(current, config) * hours
            inverter = max(config.inverter_limit_kw, 0) * hours
            export_limit = min(
                max(config.export_limit_kw, 0) * hours,
                inverter,
            )
            charge_limit = max(config.max_charge_kw, 0) * hours
            discharge_limit = max(config.max_discharge_kw, 0) * hours
            grid_import = solar_home = solar_battery = solar_export = 0.0
            grid_battery = battery_home = battery_export = curtailed = 0.0
            actions: list[str] = []

            if current.cheap_period_confirmed:
                grid_import = load_kwh
                target = capacity * _overnight_target(current, config) / 100
                solar_left = solar_kwh
                if rate <= 0:
                    charge = min(
                        solar_left,
                        charge_limit,
                        max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                    )
                    solar_battery = charge * config.charge_efficiency
                    battery += solar_battery
                    solar_left -= charge
                    if charge:
                        actions.append("store solar")
                grid_charge = min(
                    max(
                        charge_limit
                        - solar_battery / max(config.charge_efficiency, 0.01),
                        0,
                    ),
                    max(target - battery, 0) / max(config.charge_efficiency, 0.01),
                )
                if config.site_import_limit_kw is not None:
                    grid_charge = min(
                        grid_charge,
                        max(
                            config.site_import_limit_kw * hours - grid_import,
                            0,
                        ),
                    )
                grid_battery = grid_charge * config.charge_efficiency
                battery += grid_battery
                grid_import += grid_charge
                if grid_charge:
                    actions.append("cheap charge")
                if rate > 0:
                    solar_export = min(solar_left, export_limit)
                    curtailed = max(solar_left - solar_export, 0)
                    if solar_export:
                        actions.append("export solar")
                else:
                    curtailed += solar_left
            else:
                solar_home = min(solar_kwh, load_kwh, inverter)
                remaining_load = max(load_kwh - solar_home, 0)
                floor = self._floor(
                    records,
                    index,
                    current,
                    config,
                    reserve,
                    capacity,
                )
                available = max(battery - floor, 0) * max(
                    config.discharge_efficiency,
                    0.01,
                )
                battery_home = min(
                    remaining_load,
                    discharge_limit,
                    available,
                    max(inverter - solar_home, 0),
                )
                battery -= battery_home / max(
                    config.discharge_efficiency,
                    0.01,
                )
                grid_import = max(remaining_load - battery_home, 0)
                if battery_home:
                    actions.append("battery to home")
                if grid_import:
                    actions.append("protected import")

                solar_left = max(solar_kwh - solar_home, 0)
                next_cheap = _next_cheap(current.timestamp, tariff)
                best_future = _best_rate(
                    rates,
                    current.timestamp + timedelta(seconds=1),
                    next_cheap,
                )
                stored_value = (
                    best_future * config.charge_efficiency * config.discharge_efficiency
                    - BATTERY_WEAR_PENCE_PER_KWH
                )
                if (
                    solar_left
                    and battery < capacity
                    and (battery < floor or stored_value > rate + 0.001)
                ):
                    charge = min(
                        solar_left,
                        charge_limit,
                        max(capacity - battery, 0)
                        / max(config.charge_efficiency, 0.01),
                    )
                    solar_battery = charge * config.charge_efficiency
                    battery += solar_battery
                    solar_left -= charge
                    if charge:
                        actions.append("store solar for higher Agile slot")
                inverter_used = solar_home + battery_home
                if rate > 0:
                    solar_export = min(
                        solar_left,
                        export_limit,
                        max(inverter - inverter_used, 0),
                    )
                    if solar_export:
                        actions.append("export solar")
                curtailed = max(solar_left - solar_export, 0)
                inverter_used += solar_export
                floor = self._floor(
                    records,
                    index,
                    current,
                    config,
                    reserve,
                    capacity,
                )
                exportable = max(battery - floor, 0) * max(
                    config.discharge_efficiency,
                    0.01,
                )
                threshold = _threshold(
                    rates,
                    current.timestamp,
                    next_cheap,
                    exportable,
                    max(config.max_discharge_kw, 0),
                )
                if rate > 0 and threshold is not None and rate + 1e-6 >= threshold:
                    battery_export = min(
                        exportable,
                        max(export_limit - solar_export, 0),
                        max(inverter - inverter_used, 0),
                        max(discharge_limit - battery_home, 0),
                    )
                    battery -= battery_export / max(
                        config.discharge_efficiency,
                        0.01,
                    )
                    if battery_export:
                        actions.append("export battery at high Agile price")

            battery = min(max(battery, reserve), capacity)
            exported = solar_export + battery_export
            totals["import_cost"] += grid_import * import_rate
            totals["income"] += exported * rate
            totals["fixed_income"] += exported * FIXED_EXPORT_PENCE
            for key, value in (
                ("grid_import", grid_import),
                ("grid_export", exported),
                ("solar", solar_kwh),
                ("solar_home", solar_home),
                ("solar_battery", solar_battery),
                ("solar_export", solar_export),
                ("grid_battery", grid_battery),
                ("battery_home", battery_home),
                ("battery_export", battery_export),
                ("curtailed", curtailed),
            ):
                totals[key] += value
            key = slot.valid_from.isoformat()
            plan = plans.setdefault(
                key,
                {
                    "valid_from": slot.valid_from.isoformat(),
                    "valid_to": slot.valid_to.isoformat(),
                    "rate_pence": round(rate, 5),
                    "grid_import_kwh": 0.0,
                    "grid_export_kwh": 0.0,
                    "solar_export_kwh": 0.0,
                    "solar_to_battery_kwh": 0.0,
                    "battery_to_home_kwh": 0.0,
                    "battery_export_kwh": 0.0,
                    "ending_soc_percent": None,
                    "actions": [],
                },
            )
            for name, value in (
                ("grid_import_kwh", grid_import),
                ("grid_export_kwh", exported),
                ("solar_export_kwh", solar_export),
                ("solar_to_battery_kwh", solar_battery),
                ("battery_to_home_kwh", battery_home),
                ("battery_export_kwh", battery_export),
            ):
                plan[name] += value
            plan["ending_soc_percent"] = round(
                100 * battery / capacity,
                1,
            )
            plan["actions"].extend(
                action for action in actions if action not in plan["actions"]
            )

        coverage = covered / intervals if intervals else 0.0
        wear = (
            totals["battery_home"] + totals["battery_export"]
        ) * BATTERY_WEAR_PENCE_PER_KWH
        standing = _standing(records)
        energy_cost = totals["import_cost"] + standing - totals["income"]
        fixed_cost = totals["import_cost"] + standing - totals["fixed_income"] + wear
        weighted = (
            totals["income"] / totals["grid_export"]
            if totals["grid_export"] > 1e-6
            else None
        )
        values = [item.value_inc_vat for item in rates]
        summary = {
            "ready": bool(covered >= 3 and coverage >= MIN_COVERAGE and rates),
            "data_coverage": round(coverage, 4),
            "energy_net_cost_pence": round(energy_cost, 2),
            "economic_net_cost_pence": round(
                energy_cost + wear,
                2,
            ),
            "import_cost_pence": round(totals["import_cost"], 2),
            "export_income_pence": round(totals["income"], 2),
            "fixed_12p_same_dispatch_income_pence": round(
                totals["fixed_income"],
                2,
            ),
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                fixed_cost - (energy_cost + wear),
                2,
            ),
            "grid_import_kwh": round(totals["grid_import"], 3),
            "grid_export_kwh": round(totals["grid_export"], 3),
            "solar_generation_kwh": round(totals["solar"], 3),
            "solar_to_home_kwh": round(totals["solar_home"], 3),
            "solar_to_battery_kwh": round(
                totals["solar_battery"],
                3,
            ),
            "solar_export_kwh": round(totals["solar_export"], 3),
            "grid_to_battery_kwh": round(
                totals["grid_battery"],
                3,
            ),
            "battery_to_home_kwh": round(
                totals["battery_home"],
                3,
            ),
            "battery_export_kwh": round(
                totals["battery_export"],
                3,
            ),
            "solar_curtailed_kwh": round(totals["curtailed"], 3),
            "battery_wear_cost_pence": round(wear, 2),
            "weighted_achieved_export_rate_pence": (
                round(weighted, 4) if weighted is not None else None
            ),
            "average_agile_rate_pence": (
                round(sum(values) / len(values), 4) if values else None
            ),
            "highest_agile_rate_pence": (round(max(values), 4) if values else None),
            "lowest_agile_rate_pence": (round(min(values), 4) if values else None),
            "ending_soc_percent": round(
                100 * battery / capacity,
                1,
            ),
        }
        payload = []
        for slot in rates:
            item = plans.get(slot.valid_from.isoformat())
            if item:
                item = dict(item)
                for name in (
                    "grid_import_kwh",
                    "grid_export_kwh",
                    "solar_export_kwh",
                    "solar_to_battery_kwh",
                    "battery_to_home_kwh",
                    "battery_export_kwh",
                ):
                    item[name] = round(float(item[name]), 3)
            else:
                item = {
                    "valid_from": slot.valid_from.isoformat(),
                    "valid_to": slot.valid_to.isoformat(),
                    "rate_pence": round(slot.value_inc_vat, 5),
                    "grid_import_kwh": None,
                    "grid_export_kwh": None,
                    "solar_export_kwh": None,
                    "solar_to_battery_kwh": None,
                    "battery_to_home_kwh": None,
                    "battery_export_kwh": None,
                    "ending_soc_percent": None,
                    "actions": ["future slot"],
                }
            payload.append(item)
        return summary, payload

    def _floor(
        self,
        records: list[Snapshot],
        index: int,
        current: Snapshot,
        config: SimulationConfig,
        reserve: float,
        capacity: float,
    ) -> float:
        """Protect forecast reserve plus demand needed before cheap power."""
        forecast_floor = reserve
        if current.forecast_minimum_precheap_soc_percent is not None:
            forecast_floor = (
                capacity
                * max(
                    float(current.forecast_minimum_precheap_soc_percent),
                    config.battery_reserve_percent,
                )
                / 100
            )
        needed_ac = 0.0
        reached_cheap = False
        for future, following in zip(
            records[index + 1 :],
            records[index + 2 :],
            strict=False,
        ):
            if future.cheap_period_confirmed:
                reached_cheap = True
                break
            hours = min(
                max(
                    (following.timestamp - future.timestamp).total_seconds(),
                    0,
                )
                / 3600,
                0.5,
            )
            load = _load(future)
            if load is not None:
                needed_ac += load * hours
        if (
            not reached_cheap
            and current.forecast_expected_house_remaining_today_kwh is not None
        ):
            needed_ac = max(
                needed_ac,
                float(current.forecast_expected_house_remaining_today_kwh),
            )
        return min(
            max(
                reserve,
                forecast_floor,
                reserve + needed_ac / max(config.discharge_efficiency, 0.01),
            ),
            capacity,
        )

    def _day_rates(self, day: date) -> list[AgileRate]:
        return [
            item
            for item in self._rates
            if item.valid_from.astimezone(LONDON).date() == day
        ]

    def _slot_payload(
        self,
        day: date,
        result: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Merge published price slots with the simulated dispatch plan."""
        plans = {
            str(item.get("valid_from")): item
            for item in (result or {}).get("slot_plan", [])
            if isinstance(item, dict)
        }
        result_slots = []
        for slot in self._day_rates(day):
            plan = plans.get(slot.valid_from.isoformat(), {})
            local = slot.valid_from.astimezone(LONDON)
            result_slots.append(
                {
                    "valid_from": slot.valid_from.isoformat(),
                    "valid_to": slot.valid_to.isoformat(),
                    "local_from": local.isoformat(),
                    "label": local.strftime("%H:%M"),
                    "rate_pence": round(slot.value_inc_vat, 5),
                    "grid_import_kwh": plan.get("grid_import_kwh"),
                    "grid_export_kwh": plan.get("grid_export_kwh"),
                    "solar_export_kwh": plan.get("solar_export_kwh"),
                    "solar_to_battery_kwh": plan.get("solar_to_battery_kwh"),
                    "battery_to_home_kwh": plan.get("battery_to_home_kwh"),
                    "battery_export_kwh": plan.get("battery_export_kwh"),
                    "ending_soc_percent": plan.get("ending_soc_percent"),
                    "actions": plan.get("actions", ["future slot"]),
                }
            )
        return result_slots

    def _periods(
        self,
        daily: dict[str, dict[str, Any]],
        today: date,
    ) -> dict[str, Any]:
        windows = {
            "yesterday": (
                today - timedelta(days=1),
                today - timedelta(days=1),
                "Yesterday",
            ),
            "7_days": (
                today - timedelta(days=6),
                today,
                "Last 7 days",
            ),
            "30_days": (
                today - timedelta(days=29),
                today,
                "Last 30 days",
            ),
        }
        output = {}
        for key, (start, end, label) in windows.items():
            output[key] = _aggregate(
                [
                    value
                    for day, value in daily.items()
                    if start <= date.fromisoformat(day) <= end
                ],
                key,
                label,
            )
        output["all_time"] = _aggregate(
            list(daily.values()),
            "all_time",
            "All tracked time",
        )
        return output

    def _tomorrow_records(
        self,
        now: datetime,
        learned: LearnedState,
        forecast: SolarForecastState,
        plan: ForecastPlanState,
        tariff: TariffSettings,
    ) -> list[Snapshot]:
        """Create tomorrow's half-hour replay from learned demand and PV forecast."""
        tomorrow = now.date() + timedelta(days=1)
        start = datetime.combine(
            tomorrow,
            time.min,
            tzinfo=LONDON,
        ).astimezone(UTC)
        end = datetime.combine(
            tomorrow + timedelta(days=1),
            time.min,
            tzinfo=LONDON,
        ).astimezone(UTC)
        load_profile = tuple(learned.predicted_house_tomorrow_hourly_kwh)
        typical = max(float(learned.typical_house_load_kw or 0.4), 0.0)
        solar = {
            item.timestamp.astimezone(LONDON).hour: max(
                float(item.solar_energy_kwh),
                0.0,
            )
            for item in forecast.hourly
            if item.timestamp.astimezone(LONDON).date() == tomorrow
        }
        records = []
        cursor = start
        while cursor <= end:
            local = cursor.astimezone(LONDON)
            house_kw = (
                max(float(load_profile[local.hour]), 0.0)
                if len(load_profile) >= 24
                else typical
            )
            cheap = _in_window(
                local.time(),
                tariff.offpeak_start,
                tariff.offpeak_end,
            )
            rate = tariff.offpeak_rate_pence if cheap else tariff.day_rate_pence
            records.append(
                Snapshot(
                    timestamp=local,
                    current_import_rate=rate,
                    next_import_rate=rate,
                    electricity_standing_charge=(tariff.standing_charge_pence),
                    off_peak=cheap,
                    intelligent_slot=False,
                    next_offpeak_start=_next_cheap(local, tariff),
                    house_load_kw=house_kw,
                    solar_power_kw=(solar.get(local.hour) if solar else None),
                    forecast_source=plan.forecast_source,
                    forecast_expected_solar_remaining_today_kwh=(
                        plan.expected_solar_tomorrow_kwh
                    ),
                    forecast_expected_house_remaining_today_kwh=(
                        plan.expected_house_tomorrow_kwh
                    ),
                    forecast_required_morning_soc_percent=(
                        plan.required_morning_soc_percent
                    ),
                    forecast_minimum_precheap_soc_percent=(
                        plan.minimum_precheap_soc_percent
                    ),
                    forecast_solar_recovery_target_percent=(
                        plan.solar_recovery_target_percent
                    ),
                    forecast_maximum_overnight_soc_percent=(
                        plan.maximum_overnight_soc_percent
                    ),
                    forecast_recharge_shortfall_kwh=(plan.recharge_shortfall_kwh),
                    forecast_recharge_target_feasible=(plan.recharge_target_feasible),
                    forecast_protection_state=plan.state,
                    forecast_confidence_percent=(plan.confidence_percent),
                )
            )
            cursor += timedelta(minutes=30)
        return records

    def _publish(self, state: dict[str, Any]) -> None:
        """Expose dashboard states without adding any control/write surface."""
        quality = state["price_quality"]
        periods = state["periods"]
        self._set(
            "sensor.kems_agile_smart_export_status",
            "Ready" if state["ready"] else "Waiting for complete data",
            {
                "friendly_name": "Agile Smart Export status",
                "region": REGION,
                "product_code": state["product_code"],
                "tariff_code": state["tariff_code"],
                "mode": state["mode"],
                "current_action": state["current_action"],
                "fixed_export_benchmark_pence": FIXED_EXPORT_PENCE,
                "battery_wear_assumption_pence_per_discharged_kwh": (
                    BATTERY_WEAR_PENCE_PER_KWH
                ),
                "last_rate_success": state["last_rate_success"],
                "last_error": state["last_error"],
            },
        )
        self._set(
            "sensor.kems_agile_export_rate_now",
            _state(state["current_rate_pence"]),
            {
                "friendly_name": "Agile Outgoing Region L rate now",
                "unit_of_measurement": "p/kWh",
                "region": REGION,
                "product_code": state["product_code"],
                "tariff_code": state["tariff_code"],
            },
        )
        self._set(
            "sensor.kems_agile_price_data_quality",
            (
                f"{quality['today_count']}/{quality['today_expected']} today · "
                f"{quality['tomorrow_count']}/{quality['tomorrow_expected']} tomorrow"
            ),
            {
                "friendly_name": "Agile Outgoing price data quality",
                **quality,
            },
        )
        self._set(
            "sensor.kems_agile_smart_export_plan",
            state["current_action"],
            {
                "friendly_name": "Agile Smart Export plan",
                "today_slots": state["today_slots"],
                "tomorrow_slots": state["tomorrow_slots"],
                "periods": periods,
                "generated_at": state["generated_at"],
            },
        )
        for key in PUBLISHED_PERIODS:
            period = periods.get(key, _empty_period(key, key))
            agile = period["agile_smart_export"]
            full = period["full_kems_forecast"]
            comparison = period["comparison"]
            for entity_id, value, name, attrs in (
                (
                    f"sensor.kems_agile_smart_export_cost_{key}",
                    agile.get("economic_net_cost_pence"),
                    f"Agile Smart Export cost {period['label']}",
                    agile,
                ),
                (
                    f"sensor.kems_full_kems_forecast_comparison_cost_{key}",
                    full.get("economic_net_cost_pence"),
                    ("Full KEMS Forecast comparison cost " f"{period['label']}"),
                    full,
                ),
                (
                    f"sensor.kems_agile_advantage_{key}",
                    comparison.get("agile_advantage_pence"),
                    f"Agile advantage {period['label']}",
                    comparison,
                ),
            ):
                self._set(
                    entity_id,
                    _state(value),
                    {
                        "friendly_name": name,
                        "unit_of_measurement": "p",
                        **attrs,
                    },
                )
            self._set(
                f"sensor.kems_full_kems_forecast_vs_agile_winner_{key}",
                comparison.get("winner") or "Unavailable",
                {
                    "friendly_name": (
                        "Full KEMS Forecast vs Agile Smart Export winner "
                        f"{period['label']}"
                    ),
                    **comparison,
                },
            )
        today = periods.get(
            "today",
            _empty_period("today", "Today"),
        )["agile_smart_export"]
        self._set(
            "sensor.kems_agile_smart_export_export_income_today",
            _state(today.get("export_income_pence")),
            {
                "friendly_name": "Agile Smart Export export income today",
                "unit_of_measurement": "p",
            },
        )
        self._set(
            "sensor.kems_agile_smart_export_weighted_rate_today",
            _state(today.get("weighted_achieved_export_rate_pence")),
            {
                "friendly_name": ("Agile Smart Export weighted achieved rate today"),
                "unit_of_measurement": "p/kWh",
            },
        )

    def _set(
        self,
        entity_id: str,
        value: Any,
        attributes: dict[str, Any],
    ) -> None:
        self._hass.states.async_set(entity_id, str(value), attributes)


def _aggregate(
    days: list[dict[str, Any]],
    key: str,
    label: str,
) -> dict[str, Any]:
    """Aggregate ready daily strategy results."""
    ready = [item for item in days if item and item.get("ready")]
    if not ready:
        return _empty_period(key, label)

    def strategy(name: str) -> dict[str, Any]:
        items = [item[name] for item in ready]
        export = sum(float(item.get("grid_export_kwh") or 0) for item in items)
        income = sum(float(item.get("export_income_pence") or 0) for item in items)
        result = {
            "ready": True,
            "energy_net_cost_pence": round(
                sum(float(item.get("energy_net_cost_pence") or 0) for item in items),
                2,
            ),
            "economic_net_cost_pence": round(
                sum(float(item.get("economic_net_cost_pence") or 0) for item in items),
                2,
            ),
            "import_cost_pence": round(
                sum(float(item.get("import_cost_pence") or 0) for item in items),
                2,
            ),
            "export_income_pence": round(income, 2),
            "grid_import_kwh": round(
                sum(float(item.get("grid_import_kwh") or 0) for item in items),
                3,
            ),
            "grid_export_kwh": round(export, 3),
            "solar_export_kwh": round(
                sum(float(item.get("solar_export_kwh") or 0) for item in items),
                3,
            ),
            "solar_to_battery_kwh": round(
                sum(float(item.get("solar_to_battery_kwh") or 0) for item in items),
                3,
            ),
            "battery_to_home_kwh": round(
                sum(float(item.get("battery_to_home_kwh") or 0) for item in items),
                3,
            ),
            "battery_export_kwh": round(
                sum(float(item.get("battery_export_kwh") or 0) for item in items),
                3,
            ),
            "battery_wear_cost_pence": round(
                sum(float(item.get("battery_wear_cost_pence") or 0) for item in items),
                2,
            ),
            "ending_soc_percent": items[-1].get("ending_soc_percent"),
            "data_coverage": round(
                sum(float(item.get("data_coverage") or 0) for item in items)
                / len(items),
                4,
            ),
        }
        if name == "agile_smart_export":
            result["fixed_12p_same_dispatch_income_pence"] = round(
                sum(
                    float(item.get("fixed_12p_same_dispatch_income_pence") or 0)
                    for item in items
                ),
                2,
            )
            result["gain_vs_fixed_12p_same_dispatch_pence"] = round(
                sum(
                    float(item.get("gain_vs_fixed_12p_same_dispatch_pence") or 0)
                    for item in items
                ),
                2,
            )
            result["weighted_achieved_export_rate_pence"] = (
                round(income / export, 4) if export > 1e-6 else None
            )
            highs = [
                float(item["highest_agile_rate_pence"])
                for item in items
                if item.get("highest_agile_rate_pence") is not None
            ]
            lows = [
                float(item["lowest_agile_rate_pence"])
                for item in items
                if item.get("lowest_agile_rate_pence") is not None
            ]
            result["highest_agile_rate_pence"] = max(highs) if highs else None
            result["lowest_agile_rate_pence"] = min(lows) if lows else None
        return result

    full = strategy("full_kems_forecast")
    agile = strategy("agile_smart_export")
    advantage = float(full["economic_net_cost_pence"]) - float(
        agile["economic_net_cost_pence"]
    )
    return {
        "key": key,
        "label": label,
        "ready": True,
        "days_included": len(ready),
        "full_kems_forecast": full,
        "agile_smart_export": agile,
        "comparison": _comparison(advantage),
    }


def _empty_period(key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ready": False,
        "days_included": 0,
        "full_kems_forecast": {"ready": False},
        "agile_smart_export": {"ready": False},
        "comparison": _comparison(None),
    }


def _comparison(advantage: float | None) -> dict[str, Any]:
    if advantage is None:
        return {
            "agile_advantage_pence": None,
            "winner": "Unavailable",
            "winner_margin_pence": None,
        }
    winner = (
        "Tie"
        if abs(advantage) < 0.01
        else ("Agile Smart Export" if advantage > 0 else "Full KEMS Forecast")
    )
    return {
        "agile_advantage_pence": round(advantage, 2),
        "winner": winner,
        "winner_margin_pence": round(abs(advantage), 2),
    }


def _quality(
    now: datetime,
    today: list[dict[str, Any]],
    tomorrow: list[dict[str, Any]],
) -> dict[str, Any]:
    """Report 46/48/50-slot completeness correctly across UK DST."""
    today_expected = _expected_slots(now.date())
    tomorrow_expected = _expected_slots(now.date() + timedelta(days=1))
    tomorrow_complete = len(tomorrow) == tomorrow_expected
    if tomorrow_complete:
        tomorrow_status = "complete"
    elif now.time() < time(16):
        tomorrow_status = "awaiting Octopus publication"
    elif now.time() < time(20):
        tomorrow_status = "Octopus publication window"
    else:
        tomorrow_status = "incomplete after publication window"
    return {
        "status": ("ready" if len(today) == today_expected else "incomplete"),
        "today_count": len(today),
        "today_expected": today_expected,
        "today_complete": len(today) == today_expected,
        "tomorrow_count": len(tomorrow),
        "tomorrow_expected": tomorrow_expected,
        "tomorrow_complete": tomorrow_complete,
        "tomorrow_status": tomorrow_status,
    }


def _current_action(
    slots: list[dict[str, Any]],
    now: datetime,
) -> str:
    now_utc = now.astimezone(UTC)
    for item in slots:
        if _dt(item["valid_from"]) <= now_utc < _dt(item["valid_to"]):
            return ", ".join(item.get("actions") or ["Hold"])
    return "Waiting for current Agile slot"


def _published_ids() -> tuple[str, ...]:
    ids = [
        "sensor.kems_agile_smart_export_status",
        "sensor.kems_agile_export_rate_now",
        "sensor.kems_agile_price_data_quality",
        "sensor.kems_agile_smart_export_plan",
        "sensor.kems_agile_smart_export_export_income_today",
        "sensor.kems_agile_smart_export_weighted_rate_today",
    ]
    for key in PUBLISHED_PERIODS:
        ids += [
            f"sensor.kems_agile_smart_export_cost_{key}",
            f"sensor.kems_full_kems_forecast_comparison_cost_{key}",
            f"sensor.kems_agile_advantage_{key}",
            f"sensor.kems_full_kems_forecast_vs_agile_winner_{key}",
        ]
    return tuple(ids)


def _threshold(
    rates: list[AgileRate],
    start: datetime,
    end: datetime,
    energy: float,
    max_kw: float,
) -> float | None:
    """Choose only the best remaining slots needed to empty exportable energy."""
    if energy <= 0 or max_kw <= 0:
        return None
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    values = sorted(
        [
            item.value_inc_vat
            for item in rates
            if start_utc <= item.valid_from < end_utc and item.value_inc_vat > 0
        ],
        reverse=True,
    )
    if not values:
        return None
    needed = max(
        1,
        math.ceil(energy / max(max_kw * 0.5, 0.001)),
    )
    return values[min(needed, len(values)) - 1]


def _best_rate(
    rates: list[AgileRate],
    start: datetime,
    end: datetime,
) -> float:
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    values = [
        item.value_inc_vat for item in rates if start_utc <= item.valid_from < end_utc
    ]
    return max(values) if values else 0.0


def _rate_at(
    rates: list[AgileRate],
    timestamp: datetime,
) -> AgileRate | None:
    current = timestamp.astimezone(UTC)
    return next(
        (item for item in rates if item.valid_from <= current < item.valid_to),
        None,
    )


def _next_cheap(
    timestamp: datetime,
    tariff: TariffSettings,
) -> datetime:
    local = timestamp.astimezone(LONDON)
    candidate = datetime.combine(
        local.date(),
        tariff.offpeak_start,
        tzinfo=LONDON,
    )
    return candidate if candidate > local else candidate + timedelta(days=1)


def _overnight_target(
    snapshot: Snapshot,
    config: SimulationConfig,
) -> float:
    value = snapshot.forecast_maximum_overnight_soc_percent
    return min(
        max(
            float(value if value is not None else 100),
            config.battery_reserve_percent,
        ),
        100,
    )


def _expected_slots(day: date) -> int:
    start = datetime.combine(
        day,
        time.min,
        tzinfo=LONDON,
    ).astimezone(UTC)
    end = datetime.combine(
        day + timedelta(days=1),
        time.min,
        tzinfo=LONDON,
    ).astimezone(UTC)
    return int(round((end - start).total_seconds() / 1800))


def _standing(records: list[Snapshot]) -> float:
    return next(
        (
            max(float(item.electricity_standing_charge), 0)
            for item in records
            if item.electricity_standing_charge is not None
        ),
        0.0,
    )


def _load(snapshot: Snapshot) -> float | None:
    value = (
        snapshot.house_load_kw
        if snapshot.house_load_kw is not None
        else snapshot.grid_import_kw
    )
    return max(float(value), 0) if value is not None else None


def _in_window(value: time, start: time, end: time) -> bool:
    return start <= value < end if start < end else value >= start or value < end


def _dedupe(rates: list[AgileRate]) -> list[AgileRate]:
    values = {(item.valid_from, item.valid_to): item for item in rates}
    return sorted(values.values(), key=lambda item: item.valid_from)


def _state(value: Any) -> str:
    return "unknown" if value is None else str(value)


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _api_dt(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _dt(value: Any) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _maybe_dt(value: Any) -> datetime | None:
    try:
        return None if value in (None, "") else _dt(value)
    except (TypeError, ValueError):
        return None
