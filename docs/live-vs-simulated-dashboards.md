# Live-versus-Simulated dashboards

The dashboard collection is designed around two parallel systems:

- **Live** — actual Octopus, Ohme and FoxESS Modbus readings.
- **Simulated** — the proposed 9.66kWp PV, KH7 7kW inverter and 56.42kWh battery
  operating against the same household demand and tariff timeline.

`kems_actual_vs_simulated.yaml` is the simplest built-in dashboard. It places
KEMS status across the full width, then shows actual and simulated columns,
power graphs, financial differences, and the paced battery-export diagnostics.

The advanced dashboard uses Power Flow Card Plus and ApexCharts. The built-in
comparison, portrait, analytics and diagnostic dashboards require no custom
cards.
