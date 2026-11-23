"""Alpha9.250 read-only Agile current-routing card labels.

Do not edit or replace the frozen Alpha7.30 current-routing runtime: both
historic bridge modules and their byte identity remain regression protected.
This presentation-only wrapper acts on the combined dashboard after every
legacy card-injection patch has run. It never changes a rolling plan, source
snapshot or physical control command.
"""

from __future__ import annotations

from . import dashboard

_CARD_MARKER = "        title: Current Agile Smart Export power routing\n"
_REPLACEMENTS = (
    (
        "        title: Current Agile Smart Export power routing",
        "        title: Current Agile routing — proposal, permitted and measured",
    ),
    (
        "| Grid import | {{ state_attr(e, 'current_grid_import_kw')",
        "| Proposed grid import (before physical guard) | {{ state_attr(e, 'current_grid_import_kw')",
    ),
    (
        "| Grid export | {{ state_attr(e, 'current_grid_export_kw')",
        "| Proposed grid export (before physical guard) | {{ state_attr(e, 'current_grid_export_kw')",
    ),
    (
        "| Battery → export | {{ state_attr(e, 'current_battery_export_kw')",
        "| Proposed battery → export (before physical guard) | {{ state_attr(e, 'current_battery_export_kw')",
    ),
    (
        "          | Agile simulated SOC now |",
        """          | Final KEMS battery export target (after physical guard) | {{ states('sensor.kems_desired_battery_export_power') }} kW |
          | Grid export measured (FoxESS CT) | {{ states('sensor.kems_grid_export') }} kW |
          | Physical SOC (FoxESS) | {{ states('sensor.kems_battery_state_of_charge') }}% |
          | Guarded conditional SOC at cheap start | {{ state_attr('sensor.kems_agile_rolling_export_plan', 'forecast_path_reconciled_ending_soc_percent') if state_attr('sensor.kems_agile_rolling_export_plan', 'forecast_path_reconciled_ending_soc_percent') is not none else '—' }}% |
          | Agile simulated SOC now |""",
    ),
    (
        "**Power basis:** one current KEMS coordinator routing snapshot. The proposal digital twin supplies current solar/routing context and the exact Agile rolling battery candidate is substituted before grid/export totals are shown.",
        "**Power basis:** one current KEMS coordinator routing snapshot; proposals are before the physical guard, final KEMS targets are post-guard, and actual grid export is FoxESS CT-measured. The values can differ during discharge ramps; measured export is not supplier settlement. Guarded SOC is conditional on predicted house demand, not a guaranteed 10% landing.",
    ),
)


def clarify_current_agile_routing_card(content: str) -> str:
    """Label existing proposal/guard/CT signals without altering Jinja sources."""
    start = content.find(_CARD_MARKER)
    if start < 0:
        return content
    end = content.find("\n      - type:", start + len(_CARD_MARKER))
    if end < 0:
        end = len(content)
    card = content[start:end]
    # Fail closed on an unfamiliar card contract, rather than partially
    # mislabelling an unknown future hardware-routing presentation.
    if any(card.count(old) != 1 for old, _ in _REPLACEMENTS):
        return content
    for old, new in _REPLACEMENTS:
        card = card.replace(old, new, 1)
    return content[:start] + card + content[end:]


def install_alpha9250_routing_card_labels() -> None:
    """Install a pure dashboard-string transform after the historic wrappers."""
    original = dashboard._combined_master_dashboard_bytes
    if getattr(original, "_kems_alpha9250_routing_labels", False):
        return

    def combined_with_guarded_routing_labels() -> bytes:
        previous = original().decode("utf-8")
        return clarify_current_agile_routing_card(previous).encode("utf-8")

    combined_with_guarded_routing_labels._kems_alpha9250_routing_labels = True
    dashboard._combined_master_dashboard_bytes = combined_with_guarded_routing_labels
