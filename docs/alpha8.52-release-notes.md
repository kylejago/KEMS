# KEMS 0.8.0-alpha8.52

Alpha8.52 is a managed-dashboard layout-only release that gives the detailed Agile slot plan enough width to remain readable in Home Assistant. It does not change optimiser, routing, settlement, accounting, Power Down, EV policy, FoxESS control, or the hardware-write boundary.

## Full-width Agile Plan view

The managed Home Assistant dashboard now has a dedicated **Agile Plan** view using Home Assistant's native `panel` layout. A single vertical stack fills the available dashboard width and contains the complete Today and Tomorrow half-hour flow tables.

Each slot remains sourced directly from the canonical Alpha8.48+ `flow_*` presentation contract and shows:

- Time
- Price
- estimated end-of-slot SOC
- Grid route and estimated kWh
- Solar route and estimated kWh
- Battery route and estimated kWh

Action and energy now stay on the same line inside each cell, for example `EXPORT · 3.90 kWh`. Display-only route abbreviations containing `EXPO` are expanded to `EXPORT`, so mixed routes read as `HOME/EXPORT` rather than `HOME/EXPO`.

The active half-hour still uses the remaining-slot estimate. Future rows still show the current continuously recalculated KEMS plan snapshot.

## Compact normal pages

The normal **KEMS** page now keeps only a narrow-card-friendly **NOW / NEXT** summary showing the current and following slot's price, estimated SOC, Grid, Solar and Battery routes and kWh.

The existing **Tomorrow** forecast overview remains in place, while its duplicated 48-row slot table is replaced by a pointer to the full-width Agile Plan view.

This avoids the confusing narrow masonry-column wrapping seen in Alpha8.51 without requiring Pi Web or any custom Lovelace card.

## Regression boundary

- Existing canonical slot-flow reconciliation remains authoritative.
- No Agile optimiser or dispatch ownership changes.
- No settlement/accounting changes.
- Power Down behaviour is unchanged.
- KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.7`.
- managed ESP32 panel remains `0.8.0-alpha8-panel.1`.
- Real FoxESS hardware writes remain blocked.
