# KEMS 0.9.0-alpha9.69 — No Paid Export shadow routing and evidence

**Release scope:** simulation and read-only observability. This update does
**not** activate the proposed shared-bus EV-grid/house-battery power-routing
controller. It preserves the reviewed Alpha9.68 Control-mode command planner
and its existing conditional Self Use, confirmed-cheap Force Charge,
MinSOC-on-grid, commissioning and restore gates.

## Changes

- Distinct proposed cheap-period floor/EV allocation planner in Simulate and
  Shadow modes. In Control mode, an independent Alpha9.69 proposal is shown
  without sending that proposal to Happy Hour, Ohme or FoxESS write backends.
- Corrected no-paid-export digital-twin EV accounting for independently
  classified inclusion/exclusion of Ohme load in the FoxESS Load Power
  reading, with unknown measurement scope explicitly nullable rather than
  double counted or presented as proved.
- Physical-source diagnostic of observed EV net allocation on the confirmed
  shared EPS/Henley bus, comparing battery discharge with non-EV household
  residual demand and grid import with measured Ohme demand. The diagnostic
  is bounded, read-only, solar-aware and refuses stale/unknown sources.
- KEMS captures Ohme report age, retains the audit with its normal five-minute
  snapshots, reports the current result and 24-hour evidence summary in
  diagnostics, and exposes a new HA diagnostic sensor.
- No new Force Discharge, import/export power-limit or direct EV charging
  command. The sticky Alpha9.69 shadow-only flag prevents any proposed
  physical write even if a downstream overlay changes the plan reason.

## What has NOT changed

The EV and house consumer units are on a shared downstream AC bus. KEMS can
measure a **net allocation**, but the readings do not establish separate
physical power feeds. The current reviewed KH7 Self Use/Force Charge/MinSOC
surface does not establish bounded concurrent battery-to-house versus
grid-to-EV dispatch. The additional target-limited below-floor charging and
shared-bus output-control path must be commissioned in a separate reviewed
live-authority change.

ESP32 panel, Pi/Web and public-site component versions are unchanged.
