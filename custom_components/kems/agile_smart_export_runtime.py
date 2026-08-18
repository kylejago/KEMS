"""Efficient Home Assistant runtime wrapper for Agile Smart Export."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .agile_smart_export import (
    LONDON,
    AgileRate,
    AgileSmartExportManager,
    _api_dt,
    _dedupe,
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


class EfficientAgileSmartExportManager(AgileSmartExportManager):
    """Avoid replaying settled history on every normal KEMS coordinator scan."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int) -> None:
        super().__init__(hass, entry_id, history_days)
        self._last_analysis: datetime | None = None

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
        today = now.astimezone(LONDON).date()
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
