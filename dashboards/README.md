# KEMS dashboard collection

These dashboards visualise the whole energy system with **Live** and **Simulated** values shown side by side.

## Files

- `kems_pre_install_comparison.yaml` — recommended before FoxESS hardware is commissioned; avoids missing live PV/battery entities.
- `kems_live_vs_simulated_advanced.yaml` — closest to the supplied mission-control screenshot. It uses custom frontend cards.
- `kems_live_vs_simulated_builtin.yaml` — side-by-side dashboard using only built-in Home Assistant cards.
- `kems_portrait_wall_display.yaml` — compact always-on portrait/tablet view.
- `kems_whole_home_analytics.yaml` — multi-tab analysis for power flow, finance, solar/export, and gas.

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

These files target the entity IDs created by KEMS v0.5.0-alpha1. Home Assistant may append `_2` if old entity-registry entries already use an ID. Verify any missing entity under **Developer Tools → States** and adjust the YAML if required.

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
