# Alpha9.73 — fast EV / Intelligent control refresh

## Purpose

The 30 September 2026 live Alpha9.72 EV test proved that the bounded whole-bus
battery hold and confirmed-cheap Force Charge path work physically, but also
exposed a remaining response delay.

At 06:29 the EV was connected but idle and the Octopus Intelligent extra-slot
signal was still off, so there was no genuine cheap-period authority to pre-arm.
When the extra slot and Ohme charging became active together at about 06:31,
the battery initially supplied part of the EV load until the next normal
coordinator scan applied the already-reviewed Alpha9.72 hold.

Alpha9.73 removes that normal polling delay.

## Behaviour

KEMS still keeps its configured normal analysis/poll interval. In addition,
meaningful state transitions from these configured source entities request an
immediate coordinator refresh:

- Ohme status;
- explicit EV connected state, when configured;
- explicit EV charging state, when configured;
- Octopus Intelligent-slot state;
- Octopus off-peak state.

Continuous EV power changes are deliberately not subscribed to, so charging
telemetry cannot create a high-frequency refresh loop.

The Home Assistant coordinator refresh debouncer remains authoritative, so
near-simultaneous Ohme and tariff changes are coalesced safely.

## Authority boundary

This is a scheduling/responsiveness change only.

It does **not**:

- treat an Intelligent extra slot as cheap before the existing corroboration
  rules pass;
- bypass the Alpha9.72 tariff/Ohme confirmation;
- broaden the reviewed FoxESS command surface;
- enable new Force Discharge, import/export-limit or paid-export writes;
- alter commissioning, Master enable, emergency stop, stale-data, island/EPS,
  physical-SOC, site-import-headroom or foxess_modbus v1.15.0 gates;
- change the normal KEMS analysis interval.

When a source transition wakes KEMS, the normal Alpha9.72 planner, EV-grid hold
and FoxESS write-authority path run exactly as before.

## Diagnostics

Diagnostics now include `control_event_refresh` with:

- whether the fast path is registered;
- the exact configured entities being watched;
- the normal poll interval;
- the most recent meaningful trigger.

This provides direct live proof that a future EV charge start was evaluated via
the event-driven path rather than waiting for the periodic scan.
