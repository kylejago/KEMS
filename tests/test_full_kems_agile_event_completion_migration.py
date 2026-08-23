"""Contracts for conservative Happy Hour completion migration."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "kems" / "agile_event_completion_migration.py"

CONF_HAPPY_HOUR_ENABLED = "weekend_happy_hour_enabled"
CONF_HAPPY_HOUR_START = "weekend_happy_hour_start"
_LAST_COMPLETED_START = "weekend_happy_hour_last_completed_start"
_LAST_COMPLETED_END = "weekend_happy_hour_last_completed_end"
_LAST_COMPLETED_DURATION = "weekend_happy_hour_last_completed_duration_hours"
_HAPPY_HOUR_CHARGE_MODE = "happy_hour_charge"


def _function_nodes(*names: str) -> ast.Module:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    wanted = set(names)
    body = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {node.name for node in body} == wanted
    return ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))


def _parse_start(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    return result if result.tzinfo is not None else result.replace(tzinfo=UTC)


def _recover(options: dict[str, Any], decisions: list[dict[str, Any]], now: datetime):
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "CONF_HAPPY_HOUR_ENABLED": CONF_HAPPY_HOUR_ENABLED,
        "CONF_HAPPY_HOUR_START": CONF_HAPPY_HOUR_START,
        "_LAST_COMPLETED_START": _LAST_COMPLETED_START,
        "_LAST_COMPLETED_END": _LAST_COMPLETED_END,
        "_LAST_COMPLETED_DURATION": _LAST_COMPLETED_DURATION,
        "_HAPPY_HOUR_CHARGE_MODE": _HAPPY_HOUR_CHARGE_MODE,
        "parse_happy_hour_start": _parse_start,
        "happy_hour_duration_hours": lambda values: int(
            values.get("weekend_happy_hour_duration_hours", 1)
        ),
    }
    exec(
        compile(
            _function_nodes("_decision_time", "_legacy_completed_event"),
            str(MODULE),
            "exec",
        ),
        namespace,
    )
    return namespace["_legacy_completed_event"](
        options,
        decisions,
        now=now,
    )


def test_completed_legacy_event_is_recovered_from_durable_shadow_audit() -> None:
    options = {
        CONF_HAPPY_HOUR_ENABLED: False,
        CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
    }
    decisions = [
        {
            "timestamp": "2026-08-23T09:00:58+01:00",
            "dispatch_mode": "happy_hour_charge",
        },
        {
            "timestamp": "2026-08-23T10:00:53+01:00",
            "dispatch_mode": "price_optimised",
        },
    ]

    recovered = _recover(
        options,
        decisions,
        datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )

    assert recovered == {
        _LAST_COMPLETED_START: "2026-08-23T08:00:00+00:00",
        _LAST_COMPLETED_END: "2026-08-23T09:00:00+00:00",
        _LAST_COMPLETED_DURATION: 1,
    }


def test_disabled_configured_event_without_charge_evidence_is_not_invented() -> None:
    recovered = _recover(
        {
            CONF_HAPPY_HOUR_ENABLED: False,
            CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
        },
        [
            {
                "timestamp": "2026-08-23T10:00:53+01:00",
                "dispatch_mode": "price_optimised",
            }
        ],
        datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert recovered is None


def test_interrupted_event_is_not_recovered_as_full_free_hour() -> None:
    recovered = _recover(
        {
            CONF_HAPPY_HOUR_ENABLED: False,
            CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
        },
        [
            {
                "timestamp": "2026-08-23T09:00:58+01:00",
                "dispatch_mode": "happy_hour_charge",
            },
            {
                "timestamp": "2026-08-23T09:30:00+01:00",
                "dispatch_mode": "price_optimised",
            },
        ],
        datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert recovered is None


def test_charge_without_post_event_transition_is_not_enough_to_claim_completion() -> None:
    recovered = _recover(
        {
            CONF_HAPPY_HOUR_ENABLED: False,
            CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
        },
        [
            {
                "timestamp": "2026-08-23T09:00:58+01:00",
                "dispatch_mode": "happy_hour_charge",
            }
        ],
        datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert recovered is None


def test_live_or_already_retained_event_is_never_migrated() -> None:
    decisions = [
        {
            "timestamp": "2026-08-23T09:00:58+01:00",
            "dispatch_mode": "happy_hour_charge",
        },
        {
            "timestamp": "2026-08-23T10:00:53+01:00",
            "dispatch_mode": "price_optimised",
        },
    ]
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)

    assert (
        _recover(
            {
                CONF_HAPPY_HOUR_ENABLED: True,
                CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
            },
            decisions,
            now,
        )
        is None
    )
    assert (
        _recover(
            {
                CONF_HAPPY_HOUR_ENABLED: False,
                CONF_HAPPY_HOUR_START: "2026-08-23T08:00:00+00:00",
                _LAST_COMPLETED_START: "2026-08-23T08:00:00+00:00",
            },
            decisions,
            now,
        )
        is None
    )


def test_migration_remains_metadata_only_and_cannot_enable_hardware_writes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "agile_alpha8" not in MODULE.name
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "async_reload(" not in source
