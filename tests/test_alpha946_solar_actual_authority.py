"""Alpha9.46 direct FoxESS daily-solar authority regression contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "alpha946_solar_actual.py"
ENTRYPOINT = KEMS / "__init__.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha946_prefers_same_device_daily_counter_and_keeps_power_fallback() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert 'str(entry.platform).casefold().strip() != "foxess_modbus"' in source
    assert "entry.device_id != preferred_device" in source
    assert 'if "today" not in normalised:' in source
    assert '"solar generation today" in normalised' in source
    assert '_SIDECAR_KEY = "actual_solar_generation_today_kwh"' in source
    assert "Snapshot.to_dict = patched_to_dict" in source
    assert "Snapshot.from_dict = classmethod(patched_from_dict)" in source
    assert "actual_solar_generation_kwh=round(direct, 3)" in source
    assert '"integrated instantaneous PV fallback"' in source
    assert "require_day_end=True" in source


def test_alpha946_retained_daily_solar_uses_home_assistant_local_day() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "dt_util.as_local(record.timestamp).date() != target_date" in source
    assert "dt_util.as_local(item[0]).hour >= 23" in source
    assert "records, dt_util.as_local(now).date(), current_snapshot" in source
    assert (
        "dt_util.as_local(now).date() == dt_util.as_local(dt_util.now()).date()"
        in source
    )


def test_alpha946_installs_before_history_refresh_and_remains_reporting_only() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.56"
    assert "Alpha9.46" in reason
    assert "Solar Generation Today" in reason
    assert "telemetry gaps" in reason
    assert entrypoint.index("install_alpha946_solar_actual()") < entrypoint.index(
        "await coordinator.async_config_entry_first_refresh()"
    )
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
