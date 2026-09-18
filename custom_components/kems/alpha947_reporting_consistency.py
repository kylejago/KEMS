"""Alpha9.47 reporting and accounting consistency compatibility layer."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_INSTALLED = False
_GBP_TEMPLATE_RE = re.compile(
    r"\{\{ \('£%\.2f' \| format\((.*?)\)\) if (.*?) else (.*?) \}\}"
)


def _number(value: Any) -> float | None:
    """Return one finite numeric value when available."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _format_compare_currency(text: str) -> str:
    """Use conventional minus-before-currency formatting in dashboard templates."""

    def replace(match: re.Match[str]) -> str:
        return (
            "{{ (('£%.2f' | format("
            + match.group(1)
            + ")) | replace('£-', '-£')) if "
            + match.group(2)
            + " else "
            + match.group(3)
            + " }}"
        )

    return _GBP_TEMPLATE_RE.sub(replace, text)


def _normalise_dashboard(payload: bytes) -> bytes:
    """Apply Alpha9.47 customer-facing wording and currency formatting."""
    text = payload.decode("utf-8")
    text = _format_compare_currency(text)
    text = text.replace("**Today total energy cost**", "**Today net energy cost**")
    text = text.replace("**TOTAL ENERGY COST**", "**NET ENERGY COST**")
    text = text.replace(
        "_Configured KEMS digital twin._",
        "_Full KEMS digital twin — simulated operation._",
    )
    return text.encode("utf-8")


def _classify_import_breakdown(
    summary: dict[str, Any],
    plan: list[dict[str, Any]],
    records: list[Any],
) -> None:
    """Attach cheap/day import energy and cost to one authoritative Agile day."""
    total_kwh = max(_number(summary.get("grid_import_kwh")) or 0.0, 0.0)
    total_cost = _number(summary.get("import_cost_pence")) or 0.0
    cheap_kwh = 0.0
    cheap_cost = 0.0

    for item in plan:
        if not isinstance(item, dict):
            continue
        imported = max(_number(item.get("grid_import_kwh")) or 0.0, 0.0)
        if imported <= 0.0:
            continue
        try:
            start = datetime.fromisoformat(str(item.get("valid_from")))
            end = datetime.fromisoformat(str(item.get("valid_to")))
        except (TypeError, ValueError):
            continue
        samples = [
            record
            for record in records
            if start <= record.timestamp < end
            and record.current_import_rate is not None
            and not getattr(record, "tariff_stale_fields", ())
        ]
        if not samples or not bool(samples[0].cheap_period_confirmed):
            continue
        rate = _number(samples[0].current_import_rate)
        cheap_kwh += imported
        if rate is not None:
            cheap_cost += imported * rate

    cheap_kwh = min(max(cheap_kwh, 0.0), total_kwh)
    day_kwh = max(total_kwh - cheap_kwh, 0.0)
    day_cost = total_cost - cheap_cost

    summary.update(
        {
            "cheap_grid_import_kwh": round(cheap_kwh, 3),
            "day_grid_import_kwh": round(day_kwh, 3),
            "cheap_import_cost_pence": round(cheap_cost, 2),
            "day_import_cost_pence": round(day_cost, 2),
        }
    )


def _sum_strategy_fields(
    result: dict[str, Any],
    days: list[dict[str, Any]],
    strategy_name: str,
) -> None:
    """Carry day-level accounting fields into period aggregates."""
    target = result.get(strategy_name)
    if not isinstance(target, dict) or not target.get("ready"):
        return
    ready = [item for item in days if item and item.get("ready")]
    items = [
        item.get(strategy_name)
        for item in ready
        if isinstance(item.get(strategy_name), dict)
    ]
    if not items:
        return
    for field, digits in (
        ("cheap_grid_import_kwh", 3),
        ("day_grid_import_kwh", 3),
        ("cheap_import_cost_pence", 2),
        ("day_import_cost_pence", 2),
        ("solar_generation_kwh", 3),
        ("solar_to_home_kwh", 3),
        ("grid_to_battery_kwh", 3),
        ("solar_curtailed_kwh", 3),
    ):
        if any(item.get(field) is not None for item in items):
            target[field] = round(
                sum(float(item.get(field) or 0.0) for item in items),
                digits,
            )


def _reconcile_solar_routes(today: dict[str, Any]) -> bool:
    """Bound all published solar destinations to authoritative generation."""
    generation = _number(today.get("solar_generation_kwh"))
    if generation is None:
        return False
    generation = max(generation, 0.0)
    home = min(max(_number(today.get("solar_to_home_kwh")) or 0.0, 0.0), generation)
    available = max(generation - home, 0.0)

    export = min(
        max(_number(today.get("solar_export_kwh")) or 0.0, 0.0),
        available,
    )
    available = max(available - export, 0.0)

    battery = min(
        max(_number(today.get("solar_to_battery_kwh")) or 0.0, 0.0),
        available,
    )
    available = max(available - battery, 0.0)
    curtailed = min(
        max(_number(today.get("solar_curtailed_kwh")) or 0.0, 0.0),
        available,
    )

    today.update(
        {
            "solar_generation_kwh": round(generation, 3),
            "solar_to_home_kwh": round(home, 3),
            "solar_export_kwh": round(export, 3),
            "solar_to_battery_kwh": round(battery, 3),
            "solar_curtailed_kwh": round(curtailed, 3),
            "solar_routing_accounting_source": (
                "authoritative generation with canonical elapsed export; "
                "remaining replay routes bounded to generation"
            ),
        }
    )
    routed = (
        float(today["solar_to_home_kwh"])
        + float(today["solar_export_kwh"])
        + float(today["solar_to_battery_kwh"])
        + float(today["solar_curtailed_kwh"])
    )
    return routed <= generation + 0.002


def _reconcile_import_totals(today: dict[str, Any]) -> bool:
    """Keep cheap/day import components exactly aligned with headline totals."""
    total_kwh = max(_number(today.get("grid_import_kwh")) or 0.0, 0.0)
    cheap_kwh = min(
        max(_number(today.get("cheap_grid_import_kwh")) or 0.0, 0.0),
        total_kwh,
    )
    day_kwh = max(total_kwh - cheap_kwh, 0.0)
    total_cost = _number(today.get("import_cost_pence")) or 0.0
    cheap_cost = _number(today.get("cheap_import_cost_pence")) or 0.0
    day_cost = total_cost - cheap_cost
    today.update(
        {
            "cheap_grid_import_kwh": round(cheap_kwh, 3),
            "day_grid_import_kwh": round(day_kwh, 3),
            "cheap_import_cost_pence": round(cheap_cost, 2),
            "day_import_cost_pence": round(day_cost, 2),
        }
    )
    return (
        abs(
            total_kwh
            - float(today["cheap_grid_import_kwh"])
            - float(today["day_grid_import_kwh"])
        )
        <= 0.002
        and abs(
            total_cost
            - float(today["cheap_import_cost_pence"])
            - float(today["day_import_cost_pence"])
        )
        <= 0.02
    )


def _install_dashboard_patch() -> None:
    from . import dashboard_pipeline

    if getattr(dashboard_pipeline, "_alpha947_reporting_patch", False):
        return
    original = dashboard_pipeline._finalise_dashboard_bytes

    def patched(payload: bytes) -> bytes:
        return _normalise_dashboard(original(payload))

    dashboard_pipeline._finalise_dashboard_bytes = patched
    dashboard_pipeline._alpha947_reporting_patch = True


def _install_agile_day_patch() -> None:
    from . import agile_smart_export as agile
    from . import agile_smart_export_runtime as runtime

    manager = runtime.EfficientAgileSmartExportManager
    if not getattr(manager, "_alpha947_reporting_patch", False):
        original_day = manager._agile_day

        def patched_day(self, records, rates, config, tariff, initial_soc):
            summary, plan = original_day(
                self, records, rates, config, tariff, initial_soc
            )
            _classify_import_breakdown(summary, plan, records)
            return summary, plan

        manager._agile_day = patched_day
        manager._alpha947_reporting_patch = True

    if not getattr(agile, "_alpha947_aggregate_patch", False):
        original_aggregate = agile._aggregate

        def patched_aggregate(days, key, label):
            result = original_aggregate(days, key, label)
            if isinstance(result, dict) and result.get("ready"):
                _sum_strategy_fields(result, days, "agile_smart_export")
            return result

        agile._aggregate = patched_aggregate
        agile._alpha947_aggregate_patch = True


def _install_live_solar_patch() -> None:
    from . import agile_live_solar_soc_continuity as live

    if getattr(live, "_alpha947_reporting_patch", False):
        return
    original = live._apply_elapsed_solar_accounting

    def patched(state, *, tracker, now):
        original(state, tracker=tracker, now=now)
        today = live._today_agile(state)
        diagnostic = state.get("current_day_settlement_reconciliation")
        if today is None or not isinstance(diagnostic, dict):
            return

        solar_ok = _reconcile_solar_routes(today)
        import_ok = _reconcile_import_totals(today)
        battery_export = max(
            _number(today.get("battery_export_kwh")) or 0.0,
            0.0,
        )
        solar_export = max(_number(today.get("solar_export_kwh")) or 0.0, 0.0)
        grid_export = round(solar_export + battery_export, 3)
        today["grid_export_kwh"] = grid_export

        checks = diagnostic.get("accounting_checks")
        checks = dict(checks) if isinstance(checks, dict) else {}
        checks["solar_destinations_within_generation"] = solar_ok
        checks["import_energy_breakdown_balance"] = import_ok
        checks["grid_export_balance"] = (
            abs(grid_export - solar_export - battery_export) <= 0.002
        )
        diagnostic.update(
            {
                "grid_export_kwh": grid_export,
                "solar_export_kwh": round(solar_export, 3),
                "accounting_checks": checks,
                "all_accounting_checks_passed": all(checks.values()),
                "solar_routing_reconciled": True,
                "solar_routing_basis": today.get("solar_routing_accounting_source"),
            }
        )

        periods = state.get("periods")
        period_today = periods.get("today") if isinstance(periods, dict) else None
        if isinstance(period_today, dict):
            live._reconcile_comparison(period_today)

    live._apply_elapsed_solar_accounting = patched
    live._alpha947_reporting_patch = True


def _install_presentation_patch() -> None:
    from dataclasses import replace

    from . import agile_current_day_presentation as presentation
    from . import coordinator

    if getattr(presentation, "_alpha947_reporting_patch", False):
        return
    original = presentation.reconciled_current_day_simulation

    def patched(simulation, state):
        result = original(simulation, state)
        agile = presentation._today_agile(state)
        if not isinstance(agile, dict):
            return result

        replacements: dict[str, float] = {}
        mapping = {
            "simulated_cheap_import_kwh": "cheap_grid_import_kwh",
            "simulated_day_import_kwh": "day_grid_import_kwh",
            "simulated_cheap_import_cost_pence": "cheap_import_cost_pence",
            "simulated_day_import_cost_pence": "day_import_cost_pence",
            "simulated_solar_generation_kwh": "solar_generation_kwh",
            "simulated_solar_to_home_kwh": "solar_to_home_kwh",
            "simulated_solar_to_battery_kwh": "solar_to_battery_kwh",
            "simulated_solar_export_kwh": "solar_export_kwh",
            "simulated_solar_curtailed_kwh": "solar_curtailed_kwh",
        }
        for field, source in mapping.items():
            value = _number(agile.get(source))
            if value is not None:
                replacements[field] = round(
                    value,
                    2 if field.endswith("_cost_pence") else 3,
                )
        return replace(result, **replacements) if replacements else result

    presentation.reconciled_current_day_simulation = patched
    coordinator.reconciled_current_day_simulation = patched
    presentation._alpha947_reporting_patch = True


def _install_lifetime_patch() -> None:
    from . import lifetime

    recorder = lifetime.LifetimeLedgerRecorder
    if getattr(recorder, "_alpha947_reporting_patch", False):
        return
    original = recorder._apply_cumulative_day

    def patched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self._tracking_date is not None and self._tracking_values:
            self._finalise_best_day(self._tracking_date, self._tracking_values)
        return result

    recorder._apply_cumulative_day = patched
    recorder._alpha947_reporting_patch = True


def _install_commissioning_patch() -> None:
    from . import commissioning, diagnostics

    if getattr(commissioning, "_alpha947_reporting_patch", False):
        return
    original = commissioning.build_commissioning_snapshot

    def patched(
        hass,
        coordinator,
        *,
        data_override: Any | None = None,
    ):
        # Alpha9.56 commissioning can be evaluated against provisional first-refresh
        # data before coordinator.data exists. Preserve that keyword through this
        # compatibility layer and leave the current bounded-control wording intact.
        return original(
            hass,
            coordinator,
            data_override=data_override,
        )

    commissioning.build_commissioning_snapshot = patched
    diagnostics.build_commissioning_snapshot = patched
    commissioning._alpha947_reporting_patch = True


def _install_backfill_patch() -> None:
    from . import agile_history_backfill as backfill

    cls = backfill.AgileHistoryBackfill
    if getattr(cls, "_alpha947_reporting_patch", False):
        return
    original = cls._publish

    def patched(
        self,
        *,
        now,
        native_days,
        backfilled_days,
        insufficient_days,
        source_entities,
        reason,
    ):
        if (
            not backfilled_days
            and len(native_days) < backfill.TARGET_DAYS
            and reason.startswith("Older replay days recovered")
        ):
            reason = (
                "No older replay days were recovered; available Home Assistant "
                "long-term statistics did not meet the daily coverage threshold"
            )
        return original(
            self,
            now=now,
            native_days=native_days,
            backfilled_days=backfilled_days,
            insufficient_days=insufficient_days,
            source_entities=source_entities,
            reason=reason,
        )

    cls._publish = patched
    cls._alpha947_reporting_patch = True


def install_alpha947_reporting_consistency() -> None:
    """Install Alpha9.47 reporting-only consistency corrections."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_dashboard_patch()
    _install_agile_day_patch()
    _install_live_solar_patch()
    _install_presentation_patch()
    _install_lifetime_patch()
    _install_commissioning_patch()
    _install_backfill_patch()
    _INSTALLED = True
