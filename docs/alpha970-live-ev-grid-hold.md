# Alpha9.70 — live EV cheap-grid battery hold (bounded existing control)

The owner wants EV charging supplied by cheap grid while the battery supplies
the non-EV house. FoxESS KH7 and Ohme share the EPS/Henley AC bus. A
house-only output limit is not yet physically proven, so **do not present the
current control as that exact split**. Instead this release makes the
whole-bus **battery-hold fallback** explicit and strengthens its import budget.
While active, the EV and house may both import from cheap grid.

## Physical live path and activation

For a confirmed normal overnight or extra Intelligent cheap period in
No Paid Export + Control mode, an active/unknown Ohme session can raise the
reviewed MinSOC-on-grid command to at least the physical battery SOC rounded
up with a one-percentage-point margin. A restart-safe session latch prevents
the requested floor from following a falling SOC downward until a fresh
positive charge-stop observation or the cheap period ends. The already-reviewed
Self Use / confirmed-cheap Force Charge controls remain the **only** hardware
writes; this release introduces no remote Force Discharge, output-power
setpoint, export/import limit, direct Ohme command, bypass to commissioning or
automatic Master enable.

When the real physical SOC, Ohme power or site load cannot be trusted, prevent
new concurrent Force Charge and show the exact hold/blocked status. If site
measurement scope is unknown, conservatively add Ohme once to Load Power for
the site-import budget. Actual grid import is an independent over-limit veto,
not an extra baseline to which battery charging is added again. A re-budgeted
safe charge can recover an old *site-headroom-only* planner failure; unrelated
preflight, freshness, EPS, emergency and ownership gates are never waived.

Happy Hour and Power Down retain higher priority; island and stale physical
SOC never authorise new EV-specific hardware writes. The physical output
response remains unproven until observed with fresh readbacks. KEMS cannot
physically isolate shared-circuit power or enforce an EV-equivalent import on
the KH7 with MinSOC alone.

## Installation and validation

- Home Assistant requires the released integration to be installed and
  restarted before this guard can operate.
- Existing explicit **Commissioned for control** and **Master control enable**
  settings must be authorised only after all required physical commissioning
  checks pass. No update silently turns them on.
- The 27 Sep 20:51 diagnostics showed 9/12 good current-session FoxESS
  telemetry/balance samples, battery power direction proven, no failures and
  Master off. A new successful stable session may reach readiness at 12
  samples; never falsify or bypass that gate.
- Inspect `sensor.kems_ev_grid_guard` and the
  `ev_grid_hold_session`, `foxess_control`, `ev_charge_trace` and
  `shared_bus_ev_evidence` diagnostics. A desired hold, service-call success,
  command-entity state or green CI is *not* a measured proof that discharge
  stopped; compare physical battery power, SOC, grid import and actual FoxESS
  MinSOC sensor through charge start, steady charging, charge stop and slot end.
- If physical discharge persists under an intended hold, or CT/Ohme/SOC
  becomes unreliable, record that as a failed physical outcome and do not
  claim full EV-grid routing is working. Use appropriately qualified
  supervision for any inverter or EPS hardware changes.

The precise house-battery / EV-grid net dispatch remains [issue #297](
https://github.com/kylejago/KEMS/issues/297) and requires a supported,
measured KH7 site-output actuator with safe watchdog/fallback semantics.
