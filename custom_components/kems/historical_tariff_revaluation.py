"""Evidence-bounded repricing of 6–11 Oct 2026 Loyal Fixed import history.

Never mutate retained physical Snapshot measurements or reported energy. Replay
each complete historical day twice and compute only its tariff-only financial
delta. The caller persists approved deltas once with a rollback audit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from math import isfinite
from typing import Any

from .kems_core import (
    PERIOD_DATA_COMPLETE_KEY,
    SimulationConfig,
    SimulationEngine,
    Snapshot,
)

START = date(2026, 10, 6)
END = date(2026, 10, 11)
OLD_DAY_PENCE = 37.17
OLD_CHEAP_PENCE = 8.0
NEW_DAY_PENCE = 35.88
NEW_CHEAP_PENCE = 6.60
MIGRATION_ID = "loyal_oct6_2026_v1"

FINANCIAL_FIELDS = {
    "import_cost_pence": "actual_import_cost_pence",
    "simulated_import_cost_pence": "simulated_import_cost_pence",
    "simulated_net_cost_pence": "simulated_cost_pence",
    "simulated_avoided_import_value_pence": "simulated_avoided_import_value_pence",
    "actual_avoided_import_value_pence": "actual_avoided_import_value_pence",
    "actual_system_value_pence": "actual_system_value_pence",
    "simulated_system_value_pence": "simulated_system_value_pence",
}

ENERGY_FIELDS = (
    "actual_grid_import_kwh",
    "actual_grid_export_kwh",
    "simulated_grid_import_kwh",
    "simulated_grid_export_kwh",
)


def corrected_2026_import_snapshot(record: Snapshot) -> Snapshot:
    """Return a financial-replay copy; never overwrite native provenance."""
    if not START <= record.timestamp.date() <= END:
        return record
    rate = record.current_import_rate
    if rate is None or "current_import_rate" in record.tariff_stale_fields:
        return record
    if abs(rate - OLD_DAY_PENCE) < 0.001:
        return replace(record, current_import_rate=NEW_DAY_PENCE)
    if abs(rate - OLD_CHEAP_PENCE) < 0.001:
        return replace(record, current_import_rate=NEW_CHEAP_PENCE)
    return record


def financial_replay_records(records: list[Snapshot]) -> list[Snapshot]:
    """Reprice read-only copies for financial history presentations."""
    return [corrected_2026_import_snapshot(item) for item in records]


def calculate_2026_tariff_financial_deltas(
    records: list[Snapshot],
    daily: dict[str, dict[str, float]],
    config: SimulationConfig,
    already_applied: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Build independently replayed day deltas; skip incomplete/unprovable days.

    Days with missing physical samples, mismatched saved import totals, invalid
    rate evidence or divergent energy replay are left untouched for review.
    """
    original = sorted(records, key=lambda item: item.timestamp)
    corrected = financial_replay_records(original)
    native_groups: dict[date, list[Snapshot]] = defaultdict(list)
    revised_groups: dict[date, list[Snapshot]] = defaultdict(list)
    for old, new in zip(original, corrected, strict=True):
        native_groups[old.timestamp.date()].append(old)
        revised_groups[new.timestamp.date()].append(new)

    proposal: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    engine_before = SimulationEngine()
    engine_after = SimulationEngine()
    for offset in range((END - START).days + 1):
        day = START + timedelta(days=offset)
        label = day.isoformat()
        if label in already_applied:
            skipped[label] = "previously applied; restart-safe"
            continue
        source = native_groups.get(day, [])
        stored = daily.get(label)
        if stored is None:
            skipped[label] = "authoritative daily ledger unavailable"
            continue
        if len(source) < 100:
            skipped[label] = "insufficient retained native samples"
            continue
        if (
            source[0].timestamp.hour > 0
            or source[0].timestamp.minute > 20
            or source[-1].timestamp.hour < 23
            or (source[-1].timestamp.hour == 23 and source[-1].timestamp.minute < 40)
        ):
            skipped[label] = "partial-day observation boundary"
            continue
        if any(
            (following.timestamp - current.timestamp).total_seconds() > 1800
            for current, following in zip(source, source[1:], strict=False)
        ):
            skipped[label] = "missing interval longer than 30 minutes"
            continue
        if stored.get(PERIOD_DATA_COMPLETE_KEY, 1.0) < 0.5:
            skipped[label] = "daily ledger explicitly incomplete"
            continue
        changed = sum(
            a is not b for a, b in zip(source, revised_groups[day], strict=True)
        )
        if not changed:
            skipped[label] = "no qualifying old tariff readings"
            continue
        # The previous day's samples provide an optional replay SOC anchor.
        old_replay = [item for item in original if item.timestamp.date() <= day]
        new_replay = [item for item in corrected if item.timestamp.date() <= day]
        old_state = engine_before.simulate_today(
            old_replay, source[-1].timestamp, config, _records_by_day=native_groups
        )
        new_state = engine_after.simulate_today(
            new_replay, source[-1].timestamp, config, _records_by_day=revised_groups
        )
        if min(old_state.data_coverage, new_state.data_coverage) < 95:
            skipped[label] = "less than 95% replay interval evidence"
            continue
        if any(
            getattr(old_state, key) is None
            or getattr(new_state, key) is None
            or abs(float(getattr(old_state, key)) - float(getattr(new_state, key)))
            > 0.005
            for key in ENERGY_FIELDS
        ):
            skipped[label] = "energy reconciliation changed during financial replay"
            continue
        stored_cost = stored.get("import_cost_pence")
        old_cost = old_state.actual_import_cost_pence
        new_cost = new_state.actual_import_cost_pence
        if stored_cost is None or old_cost is None or new_cost is None:
            skipped[label] = "missing import cost audit"
            continue
        if abs(float(stored_cost) - float(new_cost)) <= 3.0:
            skipped[label] = "import cost already reflects corrected rates"
            continue
        if abs(float(stored_cost) - float(old_cost)) > max(
            5.0, abs(float(old_cost)) * 0.02
        ):
            skipped[label] = "saved import cost differs from original replay"
            continue
        deltas: dict[str, float] = {}
        if any(
            not isfinite(float(getattr(old_state, field, 0) or 0))
            or not isfinite(float(getattr(new_state, field, 0) or 0))
            for field in FINANCIAL_FIELDS.values()
        ):
            skipped[label] = "non-finite financial evidence"
            continue
        for ledger_key, state_key in FINANCIAL_FIELDS.items():
            old_value = getattr(old_state, state_key)
            new_value = getattr(new_state, state_key)
            if old_value is None or new_value is None:
                break
            delta = round(float(new_value) - float(old_value), 6)
            if abs(delta) > 3000:
                break
            deltas[ledger_key] = delta
        if len(deltas) != len(FINANCIAL_FIELDS):
            skipped[label] = "incomplete or implausible financial delta"
            continue
        proposal[label] = {
            "deltas": deltas,
            "original_import_cost_pence": round(float(stored_cost), 3),
            "original_replay_import_cost_pence": round(float(old_cost), 3),
            "corrected_replay_import_cost_pence": round(float(new_cost), 3),
            "repriced_samples": changed,
            "native_samples": len(source),
            "audit": MIGRATION_ID,
        }
    return proposal, skipped
