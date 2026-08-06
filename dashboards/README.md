# KEMS dashboard collection

These dashboards visualise the whole energy system with **Live** and **Simulated** values shown side by side.

## Files

- `kems_actual_vs_simulated.yaml` — full-width built-in comparison with KH7 paced-export and Octoplus Power Down diagnostics.
- `kems_pre_install_comparison.yaml` — recommended before FoxESS hardware is commissioned; avoids missing live PV/battery entities.
- `kems_live_vs_simulated_advanced.yaml` — closest to the supplied mission-control screenshot. It uses custom frontend cards.
- `kems_live_vs_simulated_builtin.yaml` — side-by-side dashboard using only built-in Home Assistant cards.
- `kems_portrait_wall_display.yaml` — compact always-on portrait/tablet view.
- `kems_whole_home_analytics.yaml` — multi-tab analysis for power flow, finance, solar/export, and gas.
- `kems_roi_lifetime_builtin.yaml` — built-in ROI, payback and lifetime ledger view.
- `kems_roi_lifetime_advanced.yaml` — advanced ROI view with financial battery and Profit Mode.
- `kems_diagnostics_all_entities.yaml` — dynamic built-in diagnostic page listing every current KEMS entity.

## Advanced dashboard requirements

Install these frontend cards through HACS before using the advanced dashboard:

- Mushroom
- ApexCharts Card
- Power Flow Card Plus

The built-in comparison, portrait, pre-install, whole-home analytics, and built-in ROI dashboards use only standard Home Assistant cards.

## Installation

1. In Home Assistant, go to **Settings → Dashboards → Add dashboard**.
2. Create a dashboard from scratch and enable **Show in sidebar**.
3. Open it, choose **Edit dashboard → three-dot menu → Raw configuration editor**.
4. Replace the starter YAML with the complete contents of one dashboard file.
5. Save.

## Entity IDs

These files target KEMS 0.7.0-alpha4. Home Assistant may append `_2` if old entity-registry entries still use an ID. The diagnostic dashboard discovers KEMS entities dynamically and is not affected by suffixes.

## Live hardware not installed yet

Until FoxESS Modbus is providing solar and battery data, Live PV/battery cards may be `unknown`. The Simulated column remains populated from the proposal system model.

## ROI and lifetime dashboards

- `kems_roi_lifetime_builtin.yaml` uses only built-in Home Assistant cards.
- `kems_roi_lifetime_advanced.yaml` adds a filling financial battery, predicted versus actual ROI, automatic Profit Mode after payback, all-time energy totals, and all-time costs/earnings.

The advanced ROI dashboard requires:

- Button Card
- Mushroom
- ApexCharts Card

Before commissioning, the financial battery uses the accumulated simulated system value. After a commissioning date is entered in KEMS options, it automatically changes to actual payback tracking. When the investment is fully recovered, it changes to `SYSTEM PAID BACK — PROFIT MODE` and shows lifetime profit.

## Complete diagnostic dashboard

`kems_diagnostics_all_entities.yaml` uses only built-in Home Assistant cards and
lists every entity shipped by KEMS 0.7.0-alpha4, including Power Down planning and reward estimates. Use it for screenshots and pair
it with Home Assistant's Download diagnostics action when reporting an issue.


## Control Lab

`kems_control_lab.yaml` shows the virtual/shadow desired command plan, whole-house island routing, EPS headroom, outage runtime, safety interlocks, and the hard live-write boundary.
