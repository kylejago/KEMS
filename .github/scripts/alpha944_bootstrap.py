from pathlib import Path
import json
import textwrap

ROOT = Path(".")
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"

if SOURCE.read_bytes() != PACKAGED.read_bytes():
    raise SystemExit("Managed dashboard source/package mismatch before Alpha9.44 patch")

text = SOURCE.read_text(encoding="utf-8")

kems_start = text.index("\n  - title: KEMS\n")
kems_end = text.index("\n  - title: Compare\n", kems_start)
kems = text[kems_start:kems_end]
marker = "\n      - type: markdown\n        title: Power history"
marker_at = kems.index(marker)

card = textwrap.dedent(r'''
      - type: markdown
        title: Weekend Happy Hour
        content: |
          {% set hh = 'switch.kems_weekend_happy_hour_auto_join' %}
          {% set status = state_attr(hh, 'status') or 'waiting_for_first_planner_update' %}
          {% set mode = states('select.kems_operating_mode') %}
          {% set booked_start = state_attr(hh, 'booked_start') %}
          {% set booked_end = state_attr(hh, 'booked_end') %}
          {% set selected_start = booked_start or state_attr(hh, 'recommended_start') %}
          {% set selected_end = booked_end or state_attr(hh, 'recommended_end') %}
          {% set rec = state_attr(hh, 'recommendation') or {} %}
          {% set benefit = state_attr(hh, 'estimated_net_benefit_pence') %}
          {% if benefit is none %}{% set benefit = rec.get('net_benefit_pence') %}{% endif %}
          {% set free_import = state_attr(hh, 'estimated_free_import_kwh') %}
          {% if free_import is none and rec %}
          {% set free_import = (rec.get('expected_house_free_import_kwh', 0) | float) + (rec.get('expected_battery_free_import_kwh', 0) | float) %}
          {% endif %}
          {% set pre_export = state_attr(hh, 'planned_pre_event_export_kwh') %}
          {% if pre_export is none %}{% set pre_export = rec.get('planned_pre_event_export_kwh') %}{% endif %}
          **Planner status:** **{{ status | replace('_', ' ') | title }}**
          **Auto join:** {{ states(hh) }}
          **Automatic event source:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'automatic_status') or 'waiting for Octopus data' }}
          **Available choices:** {{ state_attr(hh, 'candidate_count') if state_attr(hh, 'candidate_count') is not none else '-' }}
          **Selected window:** {{ selected_start or '-' }}{% if selected_end %} to {{ selected_end }}{% endif %}
          **Agile price coverage:** import {{ (state_attr(hh, 'import_price_coverage_percent') ~ '%') if state_attr(hh, 'import_price_coverage_percent') is not none else '-' }} / export {{ (state_attr(hh, 'export_price_coverage_percent') ~ '%') if state_attr(hh, 'export_price_coverage_percent') is not none else '-' }}
          **Expected free import:** {{ (free_import ~ ' kWh') if free_import is not none else '-' }}
          **Expected battery free charge:** {{ (rec.get('expected_battery_free_import_kwh') ~ ' kWh') if rec.get('expected_battery_free_import_kwh') is not none else '-' }}
          **Planned pre-event export:** {{ (pre_export ~ ' kWh') if pre_export is not none else '-' }}
          **Estimated net benefit:** {{ ('GBP %.2f' | format((benefit | float) / 100)) if benefit is not none else '-' }}

          {% if status == 'booked' and booked_start and booked_end %}
          {% set bs = as_datetime(booked_start) %}
          {% set be = as_datetime(booked_end) %}
          {% if bs and be %}
          **Event phase:** **{{ 'Booked - preparing' if now() < bs else 'Active' if now() < be else 'Completed' }}**
          {% endif %}
          {% endif %}

          {% if mode | lower != 'control' %}
          **Booking authority:** **Simulation/read-only - KEMS will not book.**
          {% elif states(hh) != 'on' %}
          **Booking authority:** Control mode is selected, but auto join is **off**.
          {% else %}
          **Booking authority:** Auto join is enabled; every independent commissioning and safety gate must still pass before KEMS calls Octopus.
          {% endif %}

          **Reward-hour import:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'current_reward_hour_import_kwh') or 0 }} / 16 kWh
          **Reward-hour remaining:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'current_reward_hour_remaining_kwh') if state_attr('sensor.kems_agile_happy_hour_plan', 'current_reward_hour_remaining_kwh') is not none else '-' }} kWh
          **Battery reservation remaining:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'battery_reserved_input_kwh_remaining') or 0 }} kWh
          **EV allowance remaining:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'ev_allowance_kwh_remaining') or 0 }} kWh

          _This is KEMS planning/booking evidence. Live Data remains measured property reality._

''').lstrip("\n")
card = textwrap.indent(card, "      ")
kems = kems[:marker_at] + "\n" + card.rstrip("\n") + kems[marker_at:]
text = text[:kems_start] + kems + text[kems_end:]

old_controls = '''              - entity: switch.kems_weekend_happy_hour_planning
                name: Manual fallback planning
              - entity: datetime.kems_weekend_happy_hour_start
'''
new_controls = '''              - entity: switch.kems_weekend_happy_hour_planning
                name: Manual fallback planning
              - entity: switch.kems_weekend_happy_hour_auto_join
                name: Auto join recommended Happy Hour
              - entity: datetime.kems_weekend_happy_hour_start
'''
if text.count(old_controls) != 1:
    raise SystemExit("Unexpected static Happy Hour controls block count")
text = text.replace(old_controls, new_controls, 1)

old_policy = '''          - type: markdown
            title: Happy Hour policy
            content: |
              **Automatic Octopus detection remains primary.** Manual planning is the fallback when KEMS cannot confidently identify the booked event.
'''
new_policy = '''          - type: markdown
            title: Happy Hour planner & policy
            content: |
              {% set hh = 'switch.kems_weekend_happy_hour_auto_join' %}
              {% set status = state_attr(hh, 'status') or 'waiting_for_first_planner_update' %}
              {% set rec = state_attr(hh, 'recommendation') or {} %}
              {% set benefit = state_attr(hh, 'estimated_net_benefit_pence') %}
              {% if benefit is none %}{% set benefit = rec.get('net_benefit_pence') %}{% endif %}
              **Planner:** **{{ status | replace('_', ' ') | title }}**
              **Discovery source:** {{ state_attr(hh, 'source') or '-' }}
              **Weekend Happy Hours available:** {{ state_attr(hh, 'weekend_happy_hours_available') if state_attr(hh, 'weekend_happy_hours_available') is not none else '-' }}
              **Reason / gate:** {{ state_attr(hh, 'join_block_reason') or '-' }}
              **Candidate slots:** {{ state_attr(hh, 'candidate_count') if state_attr(hh, 'candidate_count') is not none else '-' }}
              **Recommended start:** {{ state_attr(hh, 'recommended_start') or state_attr(hh, 'booked_start') or '-' }}
              **Recommended end:** {{ state_attr(hh, 'recommended_end') or state_attr(hh, 'booked_end') or '-' }}
              **Import price coverage:** {{ (state_attr(hh, 'import_price_coverage_percent') ~ '%') if state_attr(hh, 'import_price_coverage_percent') is not none else '-' }}
              **Export price coverage:** {{ (state_attr(hh, 'export_price_coverage_percent') ~ '%') if state_attr(hh, 'export_price_coverage_percent') is not none else '-' }}
              **Battery free charge:** {{ (rec.get('expected_battery_free_import_kwh') ~ ' kWh') if rec.get('expected_battery_free_import_kwh') is not none else '-' }}
              **Free house import:** {{ (rec.get('expected_house_free_import_kwh') ~ ' kWh') if rec.get('expected_house_free_import_kwh') is not none else '-' }}
              **Solar opportunity:** {{ (rec.get('expected_solar_opportunity_kwh') ~ ' kWh') if rec.get('expected_solar_opportunity_kwh') is not none else '-' }}
              **Planned pre-event export:** {{ (state_attr(hh, 'planned_pre_event_export_kwh') ~ ' kWh') if state_attr(hh, 'planned_pre_event_export_kwh') is not none else ((rec.get('planned_pre_event_export_kwh') ~ ' kWh') if rec.get('planned_pre_event_export_kwh') is not none else '-') }}
              **Estimated net benefit:** {{ ('GBP %.2f' | format((benefit | float) / 100)) if benefit is not none else '-' }}
              **External booking authority now:** {{ 'PERMITTED' if state_attr(hh, 'external_join_authority') else 'blocked' }}

              {% set choices = state_attr(hh, 'evaluated_candidates') or [] %}
              {% if choices %}
              | Candidate | Net benefit | Free battery | Pre-event export |
              |---|---:|---:|---:|
              {% for c in choices %}
              | {{ c.get('start', '-') }} | GBP {{ '%.2f' | format((c.get('net_benefit_pence', 0) | float) / 100) }} | {{ c.get('expected_battery_free_import_kwh', '-') }} kWh | {{ c.get('planned_pre_event_export_kwh', '-') }} kWh |
              {% endfor %}
              {% endif %}

              **Automatic Octopus detection remains primary.** Manual planning is the fallback when KEMS cannot confidently identify the booked event.
'''
if text.count(old_policy) != 1:
    raise SystemExit("Unexpected Happy Hour policy card count")
text = text.replace(old_policy, new_policy, 1)

SOURCE.write_text(text, encoding="utf-8")
PACKAGED.write_text(text, encoding="utf-8")

test = ROOT / "tests" / "test_alpha944_happy_hour_dashboard_observability.py"
test.write_text(r'''# Alpha9.44 managed-dashboard Weekend Happy Hour observability contract.

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def _dashboard() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_alpha944_kems_surfaces_happy_hour_without_live_data_pollution() -> None:
    content = _dashboard()
    live = content.split("\n  - title: Live Data\n", 1)[1].split("\n  - title: KEMS\n", 1)[0]
    kems = content.split("\n  - title: KEMS\n", 1)[1].split("\n  - title: Compare\n", 1)[0]
    assert "title: Weekend Happy Hour" in kems
    assert "switch.kems_weekend_happy_hour_auto_join" in kems
    for item in (
        "recommended_start",
        "recommended_end",
        "candidate_count",
        "import_price_coverage_percent",
        "export_price_coverage_percent",
        "estimated_free_import_kwh",
        "planned_pre_event_export_kwh",
        "estimated_net_benefit_pence",
        "expected_battery_free_import_kwh",
        "current_reward_hour_import_kwh",
    ):
        assert item in kems
    assert "Simulation/read-only - KEMS will not book." in kems
    assert "Booked - preparing" in kems
    assert "Active" in kems
    assert "Completed" in kems
    assert "switch.kems_weekend_happy_hour_auto_join" not in live
    assert "Weekend Happy Hour" not in live


def test_alpha944_system_exposes_auto_join_economics_and_safety() -> None:
    system = _dashboard().split("\n  - title: System\n", 1)[1]
    assert "Auto join recommended Happy Hour" in system
    assert "title: Happy Hour planner & policy" in system
    assert "join_block_reason" in system
    assert "evaluated_candidates" in system
    assert "expected_house_free_import_kwh" in system
    assert "expected_solar_opportunity_kwh" in system
    assert "external_join_authority" in system
    assert "16 kWh per reward hour" in system
    assert "Ohme control is opt-in" in system


def test_alpha944_dashboard_is_packaged_identically() -> None:
    assert PACKAGED.read_bytes() == SOURCE.read_bytes()


def test_alpha944_release_identity_and_scope() -> None:
    manifest = json.loads((ROOT / "custom_components" / "kems" / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    reason = str(bundle["maintenance"]["reason"])
    assert manifest["version"] == "0.9.0-alpha9.44"
    assert reason.startswith("Alpha9.44")
    assert "dashboard/observability only" in reason
    assert "Happy Hour scoring or joining logic" in reason
    assert "FoxESS hardware-write authority" in reason
''', encoding="utf-8")

manifest_path = ROOT / "custom_components" / "kems" / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest["version"] != "0.9.0-alpha9.43":
    raise SystemExit("Unexpected starting KEMS version: " + manifest["version"])
manifest["version"] = "0.9.0-alpha9.44"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

bundle_path = ROOT / "release" / "kems-bundle.template.json"
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
old_reason = str(bundle["maintenance"]["reason"])
reason = (
    "Alpha9.44 brings the Alpha9.40 Weekend Happy Hour planner and auto-join observability onto the authoritative managed customer dashboard. "
    "The KEMS view now surfaces planner and booking status, recommended or booked window, candidate count, Agile price coverage, expected free import, battery free charge, planned pre-event export, estimated net benefit and the active reward-hour budget, with an explicit read-only booking message outside Control mode and a booked/preparing/active/completed display derived from persisted booking evidence. "
    "System settings now expose the existing opt-in auto-join switch beside manual fallback and Ohme controls and show the same planner economics and safety evidence. "
    "This is dashboard/observability only: no optimiser allocation, Happy Hour scoring or joining logic, tariff policy, SOC arithmetic, Power Down, commissioning, control eligibility, Ohme authority or FoxESS hardware-write authority changes; real hardware writes remain hard-blocked."
)
bundle["maintenance"]["reason"] = reason + " " + old_reason
bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")

for path in sorted((ROOT / "tests").glob("test_*.py")):
    data = path.read_text(encoding="utf-8")
    updated = data.replace("0.9.0-alpha9.43", "0.9.0-alpha9.44")
    updated = updated.replace(
        'reason.startswith("Alpha9.43")',
        'reason.startswith("Alpha9.44")',
    )
    if updated != data:
        path.write_text(updated, encoding="utf-8")

print("Alpha9.44 dashboard patch applied")
