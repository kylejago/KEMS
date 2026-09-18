"""Alpha9.47 customer reporting/accounting consistency contracts."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "alpha947_reporting_consistency.py"
ENTRYPOINT = KEMS / "__init__.py"
MANIFEST = KEMS / "manifest.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("alpha947_reporting_test", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alpha947_compare_currency_and_wording_are_customer_clear() -> None:
    module = _load_module()
    payload = (
        b"**Today total energy cost**\n"
        b"# {{ ('\xc2\xa3%.2f' | format("
        b"(kems.get('total_energy_cost_pence') | float) / 100)) "
        b"if kems.get('total_energy_cost_pence') is not none else "
        b"'\xe2\x80\x94' }}\n"
        b"_Configured KEMS digital twin._\n"
    )

    rendered = module._normalise_dashboard(payload).decode("utf-8")

    assert "**Today net energy cost**" in rendered
    assert "replace('\u00a3-', '-\u00a3')" in rendered
    assert "_Full KEMS digital twin \u2014 simulated operation._" in rendered


def test_alpha947_import_breakdown_reconciles_to_authoritative_totals() -> None:
    module = _load_module()
    start = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    summary = {"grid_import_kwh": 41.723, "import_cost_pence": 145.75}
    plan = [
        {
            "valid_from": start.isoformat(),
            "valid_to": (start + timedelta(minutes=30)).isoformat(),
            "grid_import_kwh": 41.723,
        }
    ]
    records = [
        SimpleNamespace(
            timestamp=start,
            current_import_rate=3.4933,
            cheap_period_confirmed=True,
            tariff_stale_fields=(),
        )
    ]

    module._classify_import_breakdown(summary, plan, records)
    assert summary["cheap_grid_import_kwh"] == 41.723
    assert summary["day_grid_import_kwh"] == 0.0
    assert (
        abs(
            summary["cheap_import_cost_pence"]
            + summary["day_import_cost_pence"]
            - summary["import_cost_pence"]
        )
        <= 0.02
    )
    assert module._reconcile_import_totals(summary) is True


def test_alpha947_import_cost_breakdown_preserves_negative_agile_costs() -> None:
    module = _load_module()
    start = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    summary = {"grid_import_kwh": 2.0, "import_cost_pence": -10.0}
    plan = [
        {
            "valid_from": start.isoformat(),
            "valid_to": (start + timedelta(minutes=30)).isoformat(),
            "grid_import_kwh": 2.0,
        }
    ]
    records = [
        SimpleNamespace(
            timestamp=start,
            current_import_rate=-5.0,
            cheap_period_confirmed=True,
            tariff_stale_fields=(),
        )
    ]

    module._classify_import_breakdown(summary, plan, records)
    assert summary["cheap_import_cost_pence"] == -10.0
    assert summary["day_import_cost_pence"] == 0.0
    assert module._reconcile_import_totals(summary) is True


def test_alpha947_solar_destinations_cannot_exceed_generation() -> None:
    module = _load_module()
    today = {
        "solar_generation_kwh": 27.183,
        "solar_to_home_kwh": 5.243,
        "solar_to_battery_kwh": 10.887,
        "solar_export_kwh": 17.651,
        "solar_curtailed_kwh": 6.661,
    }

    assert module._reconcile_solar_routes(today) is True
    routed = sum(
        float(today[key])
        for key in (
            "solar_to_home_kwh",
            "solar_to_battery_kwh",
            "solar_export_kwh",
            "solar_curtailed_kwh",
        )
    )
    assert routed <= float(today["solar_generation_kwh"]) + 0.002
    assert today["solar_export_kwh"] == 17.651
    assert today["solar_to_battery_kwh"] == 4.289
    assert today["solar_curtailed_kwh"] == 0.0


def test_alpha947_installs_before_first_refresh_and_stays_reporting_only() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(manifest["version"])
    prefix = "0.9.0-alpha9."

    assert version.startswith(prefix)
    assert int(version.removeprefix(prefix)) >= 48
    assert entrypoint.index(
        "install_alpha947_reporting_consistency()"
    ) < entrypoint.index("await coordinator.async_config_entry_first_refresh()")
    assert (
        "self._finalise_best_day(self._tracking_date, self._tracking_values)" in source
    )
    assert "data_override: Any | None = None" in source
    assert "data_override=data_override" in source
    assert "Real inverter writes remain hard-blocked until" not in source
    assert "No older replay days were recovered" in source
    assert "solar_destinations_within_generation" in source
    assert "import_energy_breakdown_balance" in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
