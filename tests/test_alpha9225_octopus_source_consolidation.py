"""Alpha9.225 Octopus consolidation: no old-provider dependence or fake discounts."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
SOURCE = ROOT / "kems_core" / "octopus_source_consolidation.py"


def _load():
    spec = importlib.util.spec_from_file_location("alpha9225_migration", SOURCE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_old_intelligent_sources_are_removed_only_from_source_mapping() -> None:
    migration = _load()
    before = {
        "intelligent_slot": "binary_sensor.octopus_intelligent_tariff_slot",
        "next_offpeak_start": "sensor.octopus_intelligent_next_start",
        "offpeak_end": "sensor.octopus_intelligent_end",
        "off_peak": "binary_sensor.octopus_energy_electricity_meter_off_peak",
        "current_import_rate": "sensor.octopus_energy_electricity_meter_current_rate",
        "current_export_rate": "sensor.octopus_energy_export_current_rate",
        "saving_session_events": "event.octopus_energy_power_down",
        "ev_status": "sensor.ohme_epod_status",
        "ev_power_kw": "sensor.ohme_epod_power",
        "battery_soc": "sensor.kh7_battery_soc",
    }
    after = migration.consolidate_octopus_sources(before)
    assert set(before) - set(after) == migration.UNVERIFIED_OHME_EXTRA_SLOT_KEYS
    assert all(after[key] == before[key] for key in after)
    assert migration.consolidate_octopus_sources(after) == after
    assert "intelligent_slot" in before  # Migration must not mutate caller state.


def test_old_sources_cannot_be_reintroduced_at_setup_or_reconfiguration() -> None:
    startup = (ROOT / "__init__.py").read_text()
    discovery = (ROOT / "entity_discovery.py").read_text()
    config = (ROOT / "config_flow.py").read_text()
    assert "consolidate_octopus_sources(original_entities)" in startup
    assert "async_validate_entity_mappings(hass, consolidated_entities)" in startup
    assert "enriched = consolidate_octopus_sources(final_validation.accepted)" in startup
    assert "if rule.key in UNVERIFIED_OHME_EXTRA_SLOT_KEYS:" in discovery
    assert "if key in UNVERIFIED_OHME_EXTRA_SLOT_KEYS:" in config
    for source in (startup, discovery, config):
        ast.parse(source)


def test_ohme_plans_and_unsupported_intelligent_source_do_not_grant_cheap() -> None:
    migration = _load()
    configured = migration.consolidate_octopus_sources(
        {
            "off_peak": "binary_sensor.octopus_energy_electricity_meter_off_peak",
            "intelligent_slot": "binary_sensor.octopus_energy_ohme_intelligent_dispatching",
        }
    )
    assert configured == {
        "off_peak": "binary_sensor.octopus_energy_electricity_meter_off_peak"
    }
    code = (ROOT / "tariff.py").read_text()
    assert "slot_signal = live_intelligent_slot is True" in code
    assert "confirmed = all(passed for _, passed in checks)" in code
    assert "if extra_slot_confirmed and not schedule_offpeak:" in code
    diagnostics = (ROOT / "diagnostics.py").read_text()
    assert '"ohme_charge_plan_proves_discount": False' in diagnostics


def test_whatsapp_still_watches_normal_offpeak_and_has_truthful_warning() -> None:
    code = (ROOT / "whatsapp_notifications.py").read_text()
    assert 'getattr(self.coordinator.entities, "off_peak", None)' in code
    assert "await self._regular_offpeak_alerts(now)" in code
    assert '"regular_offpeak_alerts_enabled"' in code
    assert "WhatsApp only reports the fault" in code
    assert "Energy control operates independently." not in code
    ast.parse(code)


def test_diagnostic_offpeak_attributes_are_explicitly_read_only() -> None:
    code = (ROOT / "diagnostics.py").read_text()
    assert '"octopus_source_consolidation"' in code
    assert '"tariff_provider": "octopus_energy"' in code
    assert '"offpeak_boundaries_reporting_only"' in code
    assert '"ohme_extra_daytime_discount": "not_supplier_confirmed_fail_closed"' in code
    ast.parse(code)
