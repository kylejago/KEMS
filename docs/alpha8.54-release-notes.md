# KEMS 0.8.0-alpha8.54

Alpha8.54 is a reporting/presentation-only maintenance release prompted by the Home Assistant field proof on 29 August 2026, when a planned network upgrade left KEMS offline for part of the day. The full-width Agile Plan correctly retained the known Octopus prices for that period, but the missing historical KEMS samples were displayed as `IDLE · 0.00 kWh`, which could be mistaken for a deliberate zero-flow plan.

## Historical runtime gaps show NO DATA

KEMS already has a retained-evidence contract for this situation: a past/completed slot whose raw action remains exactly `future slot` means no KEMS decision/sample was retained for that half-hour. Alpha8.54 reuses that existing truth rather than inferring missing data from zero values.

On the Home Assistant Agile Plan table, only a row with both of these properties is treated as a runtime/data gap:

- canonical flow basis is `settled/replayed KEMS slot`; and
- retained raw actions are exactly `["future slot"]`.

For those rows:

- Price remains visible when Octopus pricing is known.
- Estimated SOC remains `—`.
- Grid, Solar and Battery each display `NO DATA · —`.

A genuine recorded historical idle/zero-flow slot continues to display `IDLE · 0.00 kWh`. Future planning rows that still carry the raw `future slot` placeholder are not labelled as outages because their canonical flow basis is forecast/rolling-plan data rather than completed settlement/replay.

## Regression proof

The Alpha8.54 regression suite renders the actual Jinja table and proves three distinct cases:

1. completed replay + `future slot` placeholder -> `NO DATA · —`;
2. completed replay + genuine recorded zero-flow evidence -> `IDLE · 0.00 kWh`;
3. future forecast/rolling row + `future slot` placeholder -> normal planned flow presentation, not `NO DATA`.

This keeps the Alpha8.53 continuous Markdown-table regression intact.

## Regression boundary

- No Agile optimiser, dispatch or routing change.
- No SOC planning or deadline behaviour change.
- No settlement or cost-accounting change.
- Power Down and Happy Hour behaviour are unchanged.
- No EV-policy change.
- No FoxESS/control change.
- Real FoxESS hardware writes remain blocked.
- KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.7`.
- Managed ESP32 panel remains `0.8.0-alpha8-panel.1`.
