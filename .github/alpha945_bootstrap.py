from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}: {count}\n{old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


source = ROOT / "custom_components" / "kems" / "happy_hour_auto_join.py"
replace_once(
    source,
    'HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR = 16.0\n_LONDON = ZoneInfo("Europe/London")\n',
    'HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR = 16.0\n'
    'HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY = 2\n'
    'HAPPY_HOUR_COORDINATOR_SESSIONS_PER_REWARD = 2\n'
    '_LONDON = ZoneInfo("Europe/London")\n',
)
replace_once(
    source,
    'def _weekend_happy_hour_count(hass: Any) -> int | None:\n',
    '''def _normalise_coordinator_happy_hour_count(value: Any) -> int | None:\n    """Convert Octopus coordinator progress units into earned one-hour rewards.\n\n    Octopus Energy 19.1 exposes ``weekend_happy_hours`` on the coordinator in\n    Power Down-success units, while its public Weekend Happy Hours sensor divides\n    that value by two. Mirror the integration's public entity semantics so KEMS\n    never displays or plans against double the customer's banked reward balance.\n    """\n    raw = _number(value)\n    if raw is None:\n        return None\n    return max(int(raw / HAPPY_HOUR_COORDINATOR_SESSIONS_PER_REWARD), 0)\n\n\ndef _event_day_redeemable_reward_hours(balance: int | None) -> int | None:\n    """Return the reward hours KEMS may consume on one Weekend Happy Hour day."""\n    if balance is None:\n        return None\n    return min(max(int(balance), 0), HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY)\n\n\ndef _reward_hours_for_candidate(candidate: HappyHourCandidate) -> int:\n    """Canonicalise one Octopus reward choice to one or two one-hour rewards."""\n    reward_hours = 2 if candidate.duration_hours >= 1.5 else 1\n    return min(reward_hours, HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY)\n\n\ndef _weekend_happy_hour_count(hass: Any) -> int | None:\n''',
)
replace_once(
    source,
    '        value = _number(getattr(data, "weekend_happy_hours", None))\n'
    '        if value is not None:\n'
    '            counts.append(max(int(value), 0))\n',
    '        value = _normalise_coordinator_happy_hour_count(\n'
    '            getattr(data, "weekend_happy_hours", None)\n'
    '        )\n'
    '        if value is not None:\n'
    '            counts.append(value)\n',
)
replace_once(
    source,
    '    coordinator_count: int | None = None\n    if not raw:\n',
    '    coordinator_count: int | None = None\n'
    '    coordinator_raw_count: int | None = None\n'
    '    if not raw:\n',
)
replace_once(
    source,
    '            value = _number(getattr(data, "weekend_happy_hours", None))\n'
    '            coordinator_count = int(value) if value is not None else None\n',
    '            raw_count = _number(getattr(data, "weekend_happy_hours", None))\n'
    '            coordinator_raw_count = (\n'
    '                max(int(raw_count), 0) if raw_count is not None else None\n'
    '            )\n'
    '            coordinator_count = _normalise_coordinator_happy_hour_count(raw_count)\n',
)
replace_once(
    source,
    '        "weekend_happy_hours_available": count,\n'
    '        "service_target_available": bool(source_entity),\n',
    '        "weekend_happy_hours_available": count,\n'
    '        "weekend_happy_hours_raw_coordinator": coordinator_raw_count,\n'
    '        "weekend_happy_hours_event_day_limit": (\n'
    '            HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY\n'
    '        ),\n'
    '        "weekend_happy_hours_redeemable_event_day": (\n'
    '            _event_day_redeemable_reward_hours(count)\n'
    '        ),\n'
    '        "weekend_happy_hours_balance_basis": (\n'
    '            "octopus public reward count"\n'
    '            if coordinator_raw_count is None\n'
    '            else "octopus coordinator progress / 2"\n'
    '        ),\n'
    '        "service_target_available": bool(source_entity),\n',
)
replace_once(
    source,
    '    duration = candidate.duration_hours\n'
    '    cap = HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR * duration\n',
    '    duration = float(_reward_hours_for_candidate(candidate))\n'
    '    cap = HAPPY_HOUR_REWARD_CAP_KWH_PER_HOUR * duration\n',
)

for relative in (
    "dashboards/kems_master_dashboard.yaml",
    "custom_components/kems/kems_master_dashboard.yaml",
):
    dashboard = ROOT / relative
    replace_once(
        dashboard,
        "          **Automatic event source:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'automatic_status') or 'waiting for Octopus data' }}\n"
        "          **Available choices:** {{ state_attr(hh, 'candidate_count') if state_attr(hh, 'candidate_count') is not none else '-' }}\n",
        "          **Automatic event source:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'automatic_status') or 'waiting for Octopus data' }}\n"
        "          **Happy Hours banked:** {{ state_attr(hh, 'weekend_happy_hours_available') if state_attr(hh, 'weekend_happy_hours_available') is not none else '-' }}\n"
        "          **Redeemable this event day:** {{ state_attr(hh, 'weekend_happy_hours_redeemable_event_day') if state_attr(hh, 'weekend_happy_hours_redeemable_event_day') is not none else '-' }} h\n"
        "          **Event-day limit:** {{ state_attr(hh, 'weekend_happy_hours_event_day_limit') or 2 }} h\n"
        "          **Available choices:** {{ state_attr(hh, 'candidate_count') if state_attr(hh, 'candidate_count') is not none else '-' }}\n",
    )
    replace_once(
        dashboard,
        "              **Weekend Happy Hours available:** {{ state_attr(hh, 'weekend_happy_hours_available') if state_attr(hh, 'weekend_happy_hours_available') is not none else '-' }}\n"
        "              **Reason / gate:** {{ state_attr(hh, 'join_block_reason') or '-' }}\n",
        "              **Happy Hours banked:** {{ state_attr(hh, 'weekend_happy_hours_available') if state_attr(hh, 'weekend_happy_hours_available') is not none else '-' }}\n"
        "              **Redeemable this event day:** {{ state_attr(hh, 'weekend_happy_hours_redeemable_event_day') if state_attr(hh, 'weekend_happy_hours_redeemable_event_day') is not none else '-' }} h\n"
        "              **Event-day limit:** {{ state_attr(hh, 'weekend_happy_hours_event_day_limit') or 2 }} h\n"
        "              **Balance basis:** {{ state_attr(hh, 'weekend_happy_hours_balance_basis') or '-' }}\n"
        "              **Reason / gate:** {{ state_attr(hh, 'join_block_reason') or '-' }}\n",
    )

(ROOT / "tests" / "test_alpha945_happy_hour_normalisation.py").write_text(
    '''"""Alpha9.45 Weekend Happy Hour balance and event-day policy contracts."""\n\nfrom __future__ import annotations\n\nfrom datetime import UTC, datetime, timedelta\nfrom types import SimpleNamespace\n\nfrom custom_components.kems.happy_hour_auto_join import (\n    HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY,\n    HappyHourCandidate,\n    _event_day_redeemable_reward_hours,\n    _reward_hours_for_candidate,\n    _weekend_happy_hour_count,\n    discover_available_happy_hours,\n)\n\n\nclass _States:\n    def __init__(self, values):\n        self._values = list(values)\n\n    def async_all(self):\n        return list(self._values)\n\n\ndef _coordinator_hass(*, raw_count: int, available_events=None):\n    data = SimpleNamespace(\n        weekend_happy_hours=raw_count,\n        available_power_up_events=list(available_events or []),\n    )\n    return SimpleNamespace(\n        states=_States([]),\n        data={\n            "octopus_energy": {\n                "A-TEST": {\n                    "POWER_UP_DOWN_COORDINATOR": SimpleNamespace(data=data),\n                }\n            }\n        },\n    )\n\n\ndef test_alpha945_coordinator_six_progress_units_are_three_rewards() -> None:\n    hass = _coordinator_hass(raw_count=6)\n    assert _weekend_happy_hour_count(hass) == 3\n\n\ndef test_alpha945_public_sensor_count_is_already_normalised() -> None:\n    state = SimpleNamespace(\n        entity_id="sensor.octopus_energy_a_test_octoplus_weekend_happy_hours",\n        state="3",\n        attributes={},\n    )\n    hass = SimpleNamespace(states=_States([state]), data={})\n    assert _weekend_happy_hour_count(hass) == 3\n\n\ndef test_alpha945_banked_balance_never_becomes_more_than_two_hours_in_one_day() -> None:\n    now = datetime(2026, 9, 18, 18, tzinfo=UTC)\n    events = []\n    for offset, hour in enumerate((9, 10, 11, 12), start=1):\n        start = datetime(2026, 9, 19, hour, tzinfo=UTC)\n        events.append(\n            {\n                "code": f"HH-{offset}",\n                "start": start,\n                "end": start + timedelta(hours=1),\n                "availability": "available",\n            }\n        )\n    hass = _coordinator_hass(raw_count=8, available_events=events)\n\n    candidates, metadata = discover_available_happy_hours(hass, now=now)\n\n    assert len(candidates) == 4\n    assert metadata["weekend_happy_hours_raw_coordinator"] == 8\n    assert metadata["weekend_happy_hours_available"] == 4\n    assert metadata["weekend_happy_hours_event_day_limit"] == 2\n    assert metadata["weekend_happy_hours_redeemable_event_day"] == 2\n    assert metadata["weekend_happy_hours_balance_basis"] == (\n        "octopus coordinator progress / 2"\n    )\n    assert _event_day_redeemable_reward_hours(1) == 1\n    assert _event_day_redeemable_reward_hours(4) == 2\n    assert HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY == 2\n\n\ndef test_alpha945_candidate_reward_accounting_is_capped_at_two_hours() -> None:\n    start = datetime(2026, 9, 19, 9, tzinfo=UTC)\n    one_hour = HappyHourCandidate(\n        code="ONE",\n        start=start,\n        end=start + timedelta(minutes=55),\n        availability="available",\n        source="test",\n    )\n    two_hour = HappyHourCandidate(\n        code="TWO",\n        start=start,\n        end=start + timedelta(minutes=125),\n        availability="available",\n        source="test",\n    )\n    assert _reward_hours_for_candidate(one_hour) == 1\n    assert _reward_hours_for_candidate(two_hour) == 2\n\n\ndef test_alpha945_dashboard_explains_banked_balance_and_daily_limit() -> None:\n    source = (\n        __import__("pathlib").Path(__file__).parents[1]\n        / "dashboards"\n        / "kems_master_dashboard.yaml"\n    ).read_text(encoding="utf-8")\n    packaged = (\n        __import__("pathlib").Path(__file__).parents[1]\n        / "custom_components"\n        / "kems"\n        / "kems_master_dashboard.yaml"\n    ).read_text(encoding="utf-8")\n    assert "Happy Hours banked" in source\n    assert "Redeemable this event day" in source\n    assert "Event-day limit" in source\n    assert "weekend_happy_hours_redeemable_event_day" in source\n    assert source == packaged\n''',
    encoding="utf-8",
)
