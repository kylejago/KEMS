# KEMS dashboard collection

KEMS ships a built-in-card managed master dashboard plus specialist dashboard examples.

## Recommended: managed KEMS Master Dashboard

`kems_master_dashboard.yaml` is the recommended dashboard for current KEMS Alpha 7 builds. It contains Overview, Live Energy, Simulation, Forecast, Full KEMS Forecast, Compare, Commissioning, Battery/Solar, Tariff/EV, Power Down, Control/EPS, Finance/History, Learning/Health, Gas, Updates and All Entities views.

The master dashboard is packaged inside `custom_components/kems/` so HACS installs it with the integration. On every KEMS config-entry setup, KEMS builds the complete managed master dashboard and atomically refreshes `/config/kems_master_dashboard.yaml` when the shipped dashboard content has changed.

This means a normal KEMS update followed by the required Home Assistant restart also updates the managed dashboard automatically.

## Full KEMS Forecast vs Agile Smart Export inside the master

`kems_agile_smart_export_builtin.yaml` contains the dedicated comparison views for **Full KEMS Forecast** and **Agile Smart Export**. KEMS packages those views with the integration and appends them automatically to the managed KEMS Master Dashboard at startup.

The master therefore gains these tabs automatically:

- **Forecast vs Agile** — live Region L Agile Outgoing rate, price-data completeness, winner/margin, import cost, export income and detailed Full KEMS Forecast vs Agile Smart Export routing.
- **Agile Price Plan** — today and tomorrow half-hour Agile prices plus the planned Smart Export action, grid export, battery export and ending SOC for each slot.
- **Agile History** — yesterday, 7-day, 30-day and all-time comparison, including cumulative Agile advantage.
- **Agile Assumptions** — Region L, 12p fixed benchmark, battery-wear allowance, physical limits and simulation-only safety boundary.

There is **no second Home Assistant dashboard registration required** for Agile Smart Export. Future KEMS updates refresh these views through the same automatically managed master dashboard.

The standalone `kems_agile_smart_export_builtin.yaml` remains in the repository as a specialist/reference dashboard and can still be installed manually if someone specifically wants the comparison separated from the master.

All automatically managed views use only built-in Home Assistant cards and therefore have no HACS frontend-card dependency.

### One-time Home Assistant registration

Home Assistant only needs the KEMS Master Dashboard registered once. Add this entry to `configuration.yaml` (merge it into any existing top-level `lovelace:` block rather than creating a duplicate key):

```yaml
lovelace:
  dashboards:
    kems-dashboard:
      mode: yaml
      filename: kems_master_dashboard.yaml
      title: KEMS
      icon: mdi:home-lightning-bolt
      show_in_sidebar: true
```

Restart Home Assistant after adding the dashboard registration. From then on, KEMS owns `/config/kems_master_dashboard.yaml` and may overwrite it during KEMS startup. Put personal dashboard experiments or customisations in different files.

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
- `kems_agile_smart_export_builtin.yaml` — specialist/reference Full KEMS Forecast vs Agile Smart Export comparison; its views are also embedded automatically in the master dashboard.
- `kems_control_lab.yaml` — desired control plan, EPS/island routing and hard live-write safety boundary.

## Advanced dashboard requirements

Only the legacy/specialist advanced dashboards require additional frontend cards. Depending on the file, install the relevant cards through HACS:

- Mushroom
- ApexCharts Card
- Power Flow Card Plus
- Button Card

The managed master dashboard and the Agile Smart Export specialist dashboard use built-in cards only.

## Manual installation of a specialist dashboard

1. In Home Assistant, go to **Settings → Dashboards → Add dashboard**.
2. Create a dashboard from scratch and enable **Show in sidebar**.
3. Open it and choose **Edit dashboard → three-dot menu → Raw configuration editor**.
4. Replace the starter YAML with the complete contents of the chosen dashboard file.
5. Save.

## Entity IDs

The managed master dashboard targets the current KEMS Alpha 7 entity set and includes a dynamic **All Entities** view. Home Assistant can retain an older entity-registry ID or append a suffix such as `_2`; use the All Entities view and Download diagnostics when investigating a mismatch.

The Agile Smart Export comparison exposes its live simulation states using the `sensor.kems_agile_*` and `sensor.kems_full_kems_forecast_*_comparison_*` namespaces. The complete slot plan and period payload are attached to `sensor.kems_agile_smart_export_plan` for the built-in master comparison views.

## Live hardware not installed yet

Until FoxESS/live solar and battery sources are providing telemetry, live PV/battery values may be `unknown`. The proposal-system simulation, forecast planning, comparison views, and Agile Smart Export shadow comparison continue to operate from retained observations, forecasts, configured system limits, and the proposal solar model where applicable.
