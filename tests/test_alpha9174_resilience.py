"""Alpha9.174 weather outage and updater resilience contract tests."""

from __future__ import annotations

import ast
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
FORECAST = ROOT / "forecasting.py"
UPDATER = ROOT / "update_orchestrator_reliable.py"


def _forecast_types():
    """Execute only HA-independent forecast cache/retry methods in isolation."""
    parsed = ast.parse(FORECAST.read_text(encoding="utf-8"))
    result = next(
        item
        for item in parsed.body
        if isinstance(item, ast.ClassDef) and item.name == "_OpenMeteoResult"
    )
    coordinator = next(
        item
        for item in parsed.body
        if isinstance(item, ast.ClassDef) and item.name == "SolarForecastCoordinator"
    )
    names = {
        "__init__",
        "_cached_open_meteo_result",
        "_async_open_meteo",
    }
    methods = [
        item
        for item in coordinator.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name in names
    ]
    assert {item.name for item in methods} == names
    isolated_coordinator = ast.ClassDef(
        name="SolarForecastCoordinator",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            result,
            isolated_coordinator,
        ],
        type_ignores=[],
    )
    namespace = {
        "__name__": __name__,
        "asyncio": asyncio,
        "dataclass": dataclass,
        "datetime": datetime,
        "timedelta": timedelta,
        "LOGGER": logging.getLogger(__name__),
    }
    exec(compile(ast.fix_missing_locations(module), str(FORECAST), "exec"), namespace)
    return namespace["SolarForecastCoordinator"], namespace["_OpenMeteoResult"]


def _coordinator():
    coordinator_type, result_type = _forecast_types()
    config = SimpleNamespace(
        open_meteo_enabled=True,
        open_meteo_refresh_minutes=15,
    )
    return coordinator_type(SimpleNamespace(), config), result_type


def test_open_meteo_outage_has_bounded_backoff_and_no_refetch_storm() -> None:
    coordinator, _ = _coordinator()
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    attempts = []

    async def fails(at):
        attempts.append(at)
        raise OSError("HTTP 503")

    coordinator._async_fetch_open_meteo = fails
    first = asyncio.run(coordinator._async_open_meteo(now))
    assert first.tomorrow_kwh is None
    assert len(attempts) == 1
    assert coordinator._open_meteo_retry_after == now + timedelta(minutes=5)

    second = asyncio.run(coordinator._async_open_meteo(now + timedelta(minutes=3)))
    assert len(attempts) == 1
    assert "retry deferred" in (second.error or "")

    asyncio.run(coordinator._async_open_meteo(now + timedelta(minutes=5)))
    assert len(attempts) == 2
    assert coordinator._open_meteo_retry_after == now + timedelta(minutes=15)


def test_open_meteo_only_uses_recent_same_day_cached_evidence() -> None:
    coordinator, result_type = _coordinator()
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    coordinator._open_meteo_cache = result_type(
        tomorrow_kwh=11.0,
        fetched_at=now - timedelta(hours=2),
    )
    good = coordinator._cached_open_meteo_result(now, "offline")
    assert good.tomorrow_kwh == 11.0
    assert good.fetched_at == now - timedelta(hours=2)
    assert "cached" in (good.error or "")

    stale = coordinator._cached_open_meteo_result(now + timedelta(hours=5), "offline")
    assert stale.tomorrow_kwh is None
    assert "no sufficiently recent" in (stale.error or "")

    overnight = coordinator._cached_open_meteo_result(
        now + timedelta(hours=13), "offline"
    )
    assert overnight.tomorrow_kwh is None


def test_success_resets_weather_backoff() -> None:
    coordinator, result_type = _coordinator()
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    coordinator._open_meteo_failures = 3
    coordinator._open_meteo_retry_after = now - timedelta(seconds=1)

    async def succeeds(at):
        return result_type(tomorrow_kwh=13.0, fetched_at=at)

    coordinator._async_fetch_open_meteo = succeeds
    answer = asyncio.run(coordinator._async_open_meteo(now))
    assert answer.tomorrow_kwh == 13.0
    assert coordinator._open_meteo_failures == 0
    assert coordinator._open_meteo_retry_after is None


def test_github_metadata_retry_is_bounded_and_http_failures_remain_strict() -> None:
    source = UPDATER.read_text(encoding="utf-8")
    assert "for attempt in range(2):" in source
    assert "except (TimeoutError, OSError, ClientError):" in source
    assert "if attempt:" in source
    assert "await asyncio.sleep(1)" in source
    assert "if response.status >= 400:" in source
    assert "hashlib.sha256(manifest_bytes)" in source


def test_release_candidate_identity() -> None:
    manifest = (ROOT / "manifest.json").read_text(encoding="utf-8")
    assert '"version": "0.9.0-alpha9.176"' in manifest
