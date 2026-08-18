# KEMS dashboard collection

KEMS ships built-in-card managed dashboards plus the earlier specialist dashboard examples.

## Recommended: managed KEMS Master Dashboard

`kems_master_dashboard.yaml` is the recommended dashboard for current KEMS Alpha 7 builds. It contains Overview, Live Energy, Simulation, Forecast, Compare, Battery/Solar, Tariff/EV, Power Down, Control/EPS, Finance/History, Learning/Health, Gas and All Entities views.

The master dashboard is also packaged inside `custom_components/kems/` so HACS installs it with the integration. On every KEMS config-entry setup, KEMS compares the packaged dashboard with `/config/kems_master_dashboard.yaml` and atomically refreshes the managed file when the shipped dashboard has changed.

This means a normal KEMS update followed by the required Home Assistant restart also updates the managed dashboard file automatically.

## Managed Full KEMS Forecast vs Agile Smart Export dashboard

`kems_agile_smart_export_builtin.yaml` is the dedicated comparison dashboard for the **Full KEMS Forecast** and **Agile Smart Export** simulations. It is also packaged with KEMS and is automatically copied to `/config/kems_agile_smart_export_dashboard.yaml` during KEMS startup.

The dashboard shows the live Region L Agile Outgoing rate, Octopus price-data completeness, today/tomorrow price slots and planned actions, the winning strategy and margin, import cost, export income, battery/solar routing, weighted achieved Agile export rate, and yesterday/7-day/30-day/all-time comparison results. Agile Smart Export remains simulation-only and does not add a FoxESS write path.

Both managed dashboards use only built-in Home Assistant cards and therefore have no HACS frontend-card dependency.

### One-time Home Assistant registration

Home Assistant must be told once that the managed files are YAML dashboards. Add these entries to `configuration.yaml` (merge them into any existing top-level `lovelace:` block rather than creating a duplicate key):

```yaml
lovelace:
  dashboards:
    kems-dashboard:
      mode: yaml
      filename: kems_master_dashboard.yaml
      title: KEMS
      icon: mdi:home-lightning-bolt
      show_in_sidebar: true

    kems-agile-smart-export:
      mode: yaml
      filename: kems_agile_smart_export_dashboard.yaml
      title: Full KEMS Forecast vs Agile Smart Export
      icon: mdi:compare-horizontal
      show_in_sidebar: true
```

Restart Home Assistant after adding the dashboard registration. From then on, KEMS owns `/config/kems_master_dashboard.yaml` and `/config/kems_agile_smart_export_dashboard.yaml` and may overwrite them during KEMS startup. Put personal dashboard experiments or customisations in different files.

## Specialist dashboard files

- `kems_actual_vs_simulated.yaml` — full-width built-in comparison with KH7 paced-export and Octoplus Power Down diagnostics.
- `kems_pre_install_comparison.yaml` — pre-install comparison before live FoxESS solar/battery telemetry is commissioned.
- `kems_live_vs_simulated_advanced.yaml` — mission-control style view using custom frontend cards.
- `kems_live_vs_simulated_builtin.yaml` — side-by-side dashboard using only built-in Home Assistant cards.
- `kems_portrait_wall_display.yaml` — compact always-on portrait/tablet view.
- `kems_whole_home_analytics.yaml` — multi-tab power-flow, finance, solar/export and gas analysis.
- `kems_roi_lifetime_builtin.yaml` — built-in ROI, payback and lifetime ledger view.
- `kems_roi_lifetime_advanced.yaml` — advanced ROI view with financial battery and Profit Mode.
- `kems_diagnostics_all_entities.yaml` — dynamic diagnostic page listing current KEMS entities.
- `kems_compare_builtin.yaml` — built-in parallel scenario comparison.
- `kems_compare_advanced.yaml` — ApexCharts/Mushroom parallel scenario analysis.
- `kems_agile_smart_export_builtin.yaml` — managed built-in Full KEMS Forecast vs Agile Smart Export comparison.
- `kems_control_lab.yaml` — desired control plan, EPS/island routing and hard live-write safety boundary.

## Advanced dashboard requirements

Only the legacy/specialist advanced dashboards require additional frontend cards. Depending on the file, install the relevant cards through HACS:

- Mushroom
- ApexCharts Card
- Power Flow Card Plus
- Button Card

The two managed dashboards do not require any of these.

## Manual installation of a specialist dashboard

1. In Home Assistant, go to **Settings → Dashboards → Add dashboard**.
2. Create a dashboard from scratch and enable **Show in sidebar**.
3. Open it and choose **Edit dashboard → three-dot menu → Raw configuration editor**.
4. Replace the starter YAML with the complete contents of the chosen dashboard file.
5. Save.

## Entity IDs

The managed master dashboard targets the current KEMS Alpha 7 entity set and includes a dynamic **All Entities** view. Home Assistant can retain an older entity-registry ID or append a suffix such as `_2`; use the All Entities view and Download diagnostics when investigating a mismatch.

The Agile Smart Export comparison exposes its live simulation states using the `sensor.kems_agile_*` and `sensor.kems_full_kems_forecast_*_comparison_*` namespaces. The complete slot plan and period payload are attached to `sensor.kems_agile_smart_export_plan` for the built-in comparison dashboard.

## Live hardware not installed yet

Until FoxESS/live solar and battery sources are providing telemetry, live PV/battery values may be `unknown`. The proposal-system simulation, forecast planning, comparison views, and Agile Smart Export shadow comparison continue to operate from retained observations, forecasts, configured system limits, and the proposal solar model where applicable.
