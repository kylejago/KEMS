"""Classify reward amounts for live ROI without changing metered flows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")


def number(value):
    try:
        n = float(value)
        return n if isfinite(n) and n >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def date_of(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return dt.astimezone(_LONDON).date().isoformat() if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def apply_reward_roi(roi, rewards):
    """Add only separate bonuses/credits, never regular Agile export income."""
    if not roi.system_installed:
        return roi
    value = float(roi.actual_value_created_total_gbp or 0) + rewards["total"] / 100
    today = float(roi.actual_value_created_today_gbp or 0) + rewards["today"] / 100
    invested = roi.net_investment_gbp
    recovered = value - roi.operating_costs_gbp
    return replace(
        roi,
        actual_value_created_total_gbp=round(value, 2),
        actual_value_created_today_gbp=round(today, 2),
        actual_roi_percent=round(100 * recovered / invested, 2) if invested > 0 else 100.0,
        actual_payback_remaining_gbp=round(max(invested - recovered, 0), 2),
        actual_net_profit_gbp=round(max(recovered - invested, 0), 2),
        happy_hour_roi_credit_gbp=round(rewards["happy"] / 100, 2),
        power_down_roi_bonus_gbp=round(rewards["power_down"] / 100, 2),
        roi_rewards_unsettled_gbp=round(rewards["unsettled"] / 100, 2),
    )
