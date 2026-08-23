"""Regression coverage for durable automatic Happy Hour evidence."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
NOW = datetime(2026, 8, 23, 18, 30, tzinfo=UTC)


def _load_retention_module():
    package_name = "kems_happy_hour_retention_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    const = ModuleType(f"{package_name}.const")
    const.DOMAIN = "kems"
    const.STORAGE_NAMESPACE = "store"
    sys.modules[f"{package_name}.const"] = const

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.happy_hour_retention",
        INTEGRATION / "happy_hour_retention.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_retention_module()
retained_happy_hour_result = MODULE.retained_happy_hour_result


def _manual(start: datetime, end: datetime, status: str) -> dict:
    return {
        "enabled": True,
        "source": "manual",
        "automatic_source_supported": True,
        "automatic_status": status,
        "start": start,
        "end": end,
        "duration_hours": (end - start).total_seconds() / 3600,
        "fair_use_cap_kwh": 16.0,
    }


def _retained(start: datetime, end: datetime) -> dict:
    return {
        "source": "octopus_energy",
        "automatic_source_supported": True,
        "source_kind": "octopus_coordinator",
        "source_account": "A-60624FB8",
        "classification_basis": (
            "code-less weekend Power Up, 1/2-hour conservative match"
        ),
        "confidence": "conservative",
        "event_ids": ["hh-1"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_hours": 1,
        "fair_use_cap_kwh": 16.0,
        "captured_at": (start - timedelta(hours=2)).isoformat(),
    }


def test_completed_automatic_event_survives_empty_upstream_feed() -> None:
    start = NOW - timedelta(hours=10, minutes=30)
    end = start + timedelta(hours=1)
    live = _manual(start, end, "no_confident_weekend_happy_hour")

    result = retained_happy_hour_result(live, _retained(start, end), now=NOW)

    assert result["source"] == "octopus_energy"
    assert result["automatic_status"] == "retained_completed"
    assert result["source_kind"] == "retained_octopus_evidence"
    assert result["retained_source_kind"] == "octopus_coordinator"
    assert result["automatic_evidence"] == "retained"
    assert result["evidence_retained"] is True
    assert result["start"] == start
    assert result["end"] == end


def test_retained_event_can_cover_feed_disappearance_before_start() -> None:
    start = NOW + timedelta(hours=3)
    end = start + timedelta(hours=1)
    live = {
        "enabled": False,
        "source": "manual",
        "automatic_source_supported": True,
        "automatic_status": "no_confident_weekend_happy_hour",
    }

    result = retained_happy_hour_result(live, _retained(start, end), now=NOW)

    assert result["source"] == "octopus_energy"
    assert result["automatic_status"] == "retained_upcoming"


def test_ambiguous_live_power_up_never_uses_retained_evidence() -> None:
    start = NOW - timedelta(hours=10)
    end = start + timedelta(hours=1)
    live = _manual(start, end, "ambiguous_upcoming_power_up_events")

    result = retained_happy_hour_result(live, _retained(start, end), now=NOW)

    assert result["source"] == "manual"
    assert result["automatic_status"] == "ambiguous_upcoming_power_up_events"
    assert result["retained_automatic_event_available"] is True


def test_newer_manual_fallback_is_not_hidden_by_old_retained_event() -> None:
    retained_start = NOW - timedelta(days=7)
    retained_end = retained_start + timedelta(hours=1)
    manual_start = NOW + timedelta(days=7)
    manual_end = manual_start + timedelta(hours=1)
    live = _manual(manual_start, manual_end, "no_confident_weekend_happy_hour")

    result = retained_happy_hour_result(
        live,
        _retained(retained_start, retained_end),
        now=NOW,
    )

    assert result["source"] == "manual"
    assert result["start"] == manual_start
    assert result["retained_automatic_event_superseded_by_manual"] is True


def test_stale_retained_event_does_not_replace_manual_fallback() -> None:
    start = NOW - timedelta(days=40)
    end = start + timedelta(hours=1)
    live = {
        "enabled": False,
        "source": "manual",
        "automatic_source_supported": True,
        "automatic_status": "no_confident_weekend_happy_hour",
    }

    result = retained_happy_hour_result(live, _retained(start, end), now=NOW)

    assert result["source"] == "manual"
    assert result["retained_automatic_event_available"] is True
    assert result["retained_automatic_event_stale"] is True


def test_live_automatic_event_remains_authoritative() -> None:
    start = NOW + timedelta(hours=2)
    end = start + timedelta(hours=1)
    live = {
        "enabled": True,
        "source": "octopus_energy",
        "automatic_source_supported": True,
        "automatic_status": "detected_upcoming",
        "start": start,
        "end": end,
    }

    result = retained_happy_hour_result(live, None, now=NOW)

    assert result["source"] == "octopus_energy"
    assert result["automatic_status"] == "detected_upcoming"
    assert result["automatic_evidence"] == "live"


def test_runtime_registry_installs_retention_after_automatic_discovery() -> None:
    compat = (INTEGRATION / "agile_alpha7_compat.py").read_text(encoding="utf-8")
    automatic = '("happy_hour_auto", "install_automatic_happy_hour")'
    retention = '("happy_hour_retention", "install_happy_hour_retention")'
    assert automatic in compat
    assert retention in compat
    assert compat.index(automatic) < compat.index(retention)


def test_dashboard_retention_copy_is_present() -> None:
    source = (INTEGRATION / "happy_hour_retention.py").read_text(encoding="utf-8")
    assert "**Evidence:**" in source
    assert "retained_octopus_evidence" in source
    assert "retained_completed" in source
