"""Alpha9.33 live ROI and managed-dashboard regression tests."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).parents[1]
ROI_ACCOUNTING = ROOT / "custom_components" / "kems" / "roi_accounting.py"
ROI_DASHBOARD = ROOT / "custom_components" / "kems" / "kems_roi_lifetime_dashboard.yaml"
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"
COORDINATOR = ROOT / "custom_components" / "kems" / "coordinator.py"


def _load_roi_accounting():
    """Load the pure ROI accounting helper without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location("kems_roi_accounting_test", ROI_ACCOUNTING)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_financial_start_rebuilds_only_real_value_from_selected_date() -> None:
    """Pre-start and simulated value must never enter real ROI payback."""
    module = _load_roi_accounting()
    totals = module.commissioned_actual_value_totals(
        {
            "2026-09-11": {
                "actual_avoided_import_value_pence": 99.0,
                "actual_system_value_pence": 109.0,
                "simulated_system_value_pence": 9999.0,
            },
            "2026-09-12": {
                "actual_avoided_import_value_pence": 110.0,
                "actual_system_value_pence": 110.0,
                "simulated_system_value_pence": 8888.0,
            },
        },
        commissioning_date=date(2026, 9, 12),
        tracking_date=date(2026, 9, 13),
        tracking_values={
            "actual_avoided_import_value_pence": 197.1,
            "actual_system_value_pence": 197.1,
            "simulated_system_value_pence": 492.9,
        },
    )
    assert totals == {
        "actual_avoided_import_value_pence": 307.1,
        "actual_system_value_pence": 307.1,
    }


def test_financial_reconciliation_preserves_signed_actual_value() -> None:
    """A genuine negative paid-export interval must remain visible in ROI."""
    module = _load_roi_accounting()
    totals = module.commissioned_actual_value_totals(
        {
            "2026-09-12": {
                "actual_avoided_import_value_pence": 100.0,
                "actual_system_value_pence": 95.0,
            }
        },
        commissioning_date=date(2026, 9, 12),
    )
    assert totals["actual_avoided_import_value_pence"] == 100.0
    assert totals["actual_system_value_pence"] == 95.0


def test_reconciliation_updates_only_financial_value_fields() -> None:
    """The startup repair must preserve physical energy and simulated evidence."""
    module = _load_roi_accounting()

    class Recorder:
        def __init__(self) -> None:
            self._daily_records = {
                "2026-09-12": {
                    "grid_export_kwh": 6.021,
                    "actual_avoided_import_value_pence": 110.0,
                    "actual_system_value_pence": 110.0,
                    "simulated_system_value_pence": 500.0,
                }
            }
            self._tracking_date = date(2026, 9, 13)
            self._tracking_values = {
                "grid_export_kwh": 15.348,
                "actual_avoided_import_value_pence": 197.1,
                "actual_system_value_pence": 197.1,
                "simulated_system_value_pence": 492.9,
            }
            self._ledger = SimpleNamespace(
                commissioning_date=None,
                actual_avoided_import_value_pence=0.0,
                actual_system_value_pence=0.0,
            )
            self.saved = 0

        async def async_save(self) -> None:
            self.saved += 1

    recorder = Recorder()
    changed = asyncio.run(
        module.async_reconcile_financial_commissioning(
            recorder,
            date(2026, 9, 12),
        )
    )
    assert changed is True
    assert recorder.saved == 1
    assert recorder._ledger.commissioning_date == date(2026, 9, 12)
    assert recorder._ledger.actual_avoided_import_value_pence == 307.1
    assert recorder._ledger.actual_system_value_pence == 307.1
    assert recorder._tracking_values["grid_export_kwh"] == 15.348
    assert recorder._tracking_values["simulated_system_value_pence"] == 492.9


def test_clearing_financial_start_returns_actual_roi_to_preinstall_state() -> None:
    """Removing the explicit financial date must deterministically clear ROI value."""
    module = _load_roi_accounting()
    recorder = SimpleNamespace(
        _daily_records={"2026-09-12": {"actual_system_value_pence": 100.0}},
        _tracking_date=None,
        _tracking_values={},
        _ledger=SimpleNamespace(
            commissioning_date=date(2026, 9, 12),
            actual_avoided_import_value_pence=80.0,
            actual_system_value_pence=100.0,
        ),
    )
    changed = asyncio.run(module.async_reconcile_financial_commissioning(recorder, None))
    assert changed is True
    assert recorder._ledger.commissioning_date is None
    assert recorder._ledger.actual_avoided_import_value_pence == 0.0
    assert recorder._ledger.actual_system_value_pence == 0.0


def test_roi_view_is_builtin_and_actual_value_focused() -> None:
    """The restored customer tab must use registered actual ROI entities."""
    content = ROI_DASHBOARD.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert [view["path"] for view in parsed["views"]] == ["roi"]
    assert "sensor.kems_actual_system_value_today" in content
    assert "sensor.kems_actual_system_value_total" in content
    assert "sensor.kems_lifetime_avoided_import_value" in content
    assert "sensor.kems_lifetime_export_income" in content
    assert "sensor.kems_actual_roi" in content
    assert "Solar used by the home counts as avoided grid-import value" in content
    assert "Simulated battery/export gains are kept out of actual payback" in content


def test_final_managed_pipeline_appends_roi_view() -> None:
    """The authoritative runtime dashboard must append the packaged ROI tab."""
    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert '"kems_roi_lifetime_dashboard.yaml"' in pipeline
    assert 'marker = "\\nviews:\\n"' in pipeline
    assert 'f"{master}\\n\\n{roi_views}"' in pipeline


def test_unpaid_export_cleanup_precedes_financial_roi_reconciliation() -> None:
    """False export money must be scrubbed before any value is backfilled."""
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    scrub = coordinator.index("await async_repair_no_paid_export_income")
    reconcile = coordinator.index("await async_reconcile_financial_commissioning")
    assert scrub < reconcile
    assert "self.settings.roi.commissioning_date" in coordinator
