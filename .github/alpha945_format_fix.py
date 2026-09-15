from pathlib import Path

path = Path("custom_components/kems/happy_hour_auto_join.py")
text = path.read_text(encoding="utf-8")
old = '''        "weekend_happy_hours_event_day_limit": (
            HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY
        ),
'''
new = '''        "weekend_happy_hours_event_day_limit": (HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY),
'''
if text.count(old) != 1:
    raise RuntimeError("Expected one Alpha9.45 formatting target")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
