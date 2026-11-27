"""Financial-only Octopus Power Down award import and exact-window deduplication."""

import json
from datetime import UTC, datetime, timedelta

from .roi_rewards import date_of
from .supplier_intervals import _utc

FORMAT = "kems-power-down-awards-v1"
FILE_NAME = "kems_power_down_awards.json"


def award_window(start, end):
    start, end = _utc(start), _utc(end)
    if (
        start is None
        or end is None
        or not start < end <= start + timedelta(days=1)
        or start.minute not in (0, 30)
        or end.minute not in (0, 30)
        or start.second
        or end.second
        or start.microsecond
        or end.microsecond
    ):
        return None
    return (start.isoformat(), end.isoformat())


def read_awards(path):
    """Read a user-supplied, local-only reference; no account credentials."""
    if not path.is_file():
        return []
    if path.stat().st_size > 1_000_000:
        raise ValueError("Power Down award file too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("Invalid Power Down award file")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError("Invalid Power Down award rows")
    accepted = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid Power Down award row")
        window = award_window(row.get("start"), row.get("end"))
        points = row.get("rewarded_octopoints")
        if (
            window is None
            or not isinstance(points, int)
            or isinstance(points, bool)
            or not 0 <= points <= 2_000_000
        ):
            raise ValueError("Invalid Power Down award row")
        if window in accepted and accepted[window] != points:
            raise ValueError("Conflicting Power Down awards")
        accepted[window] = points
    return [
        {"start": start, "end": end, "rewarded_octopoints": points}
        for (start, end), points in sorted(accepted.items())
    ]


def reconcile_window_aliases(ledger, events):
    """Migrate imported window identities when KEMS learns the provider ID."""
    known = {}
    for event in events:
        key = getattr(event, "session_id", None)
        window = award_window(
            getattr(event, "session_start", None),
            getattr(event, "session_end", None),
        )
        if key and window:
            known.setdefault(window, set()).add(str(key))
    changed = False
    for (start, end), keys in known.items():
        alias = f"octopus-window:{start}|{end}"
        if alias not in ledger or len(keys) != 1:
            continue
        key = next(iter(keys))
        previous = ledger.get(key, {})
        previous_window = award_window(previous.get("start"), previous.get("end"))
        if previous_window is not None and previous_window != (start, end):
            continue
        if previous.get("supplier_settled") is not True:
            ledger[key] = ledger[alias]
        del ledger[alias]
        changed = True
    return changed


def apply_imported_awards(ledger, events, rows, *, now):
    """Match known IDs by exact window; keep unknown events financially separate.

    A local snapshot never overwrites an existing confirmed supplier award.
    Unidentified legacy ledger records on the same date fail closed.
    """
    changed = reconcile_window_aliases(ledger, events)
    known = {}
    for event in events:
        key = getattr(event, "session_id", None)
        window = award_window(
            getattr(event, "session_start", None),
            getattr(event, "session_end", None),
        )
        if key and window:
            known.setdefault(window, set()).add(str(key))
    for row in rows:
        window = award_window(row.get("start"), row.get("end"))
        points = row.get("rewarded_octopoints")
        if (
            window is None
            or not isinstance(points, int)
            or isinstance(points, bool)
            or not 0 <= points <= 2_000_000
            or datetime.fromisoformat(window[1]) > now.astimezone(UTC)
        ):
            continue
        start, end = window
        day = date_of(end)
        keys = set(known.get(window, ()))
        for key, receipt in ledger.items():
            if award_window(receipt.get("start"), receipt.get("end")) == window:
                keys.add(key)
        if len(keys) > 1:
            continue
        if keys:
            key = next(iter(keys))
        else:
            if any(
                receipt.get("day") == day
                and award_window(receipt.get("start"), receipt.get("end")) is None
                for receipt in ledger.values()
            ):
                continue
            key = f"octopus-window:{start}|{end}"
        previous = ledger.get(key, {})
        previous_window = award_window(previous.get("start"), previous.get("end"))
        if previous_window is not None and previous_window != window:
            continue
        if previous.get("supplier_settled") is True:
            continue
        saved = {
            "day": day,
            "start": start,
            "end": end,
            "pence": points / 8.0,
            "supplier_settled": True,
            "basis": "supplier_awarded_octopoints",
            "award_source": "local_octopus_account_history",
            "awarded_octopoints": points,
        }
        if previous != saved:
            ledger[key] = saved
            changed = True
    return changed
