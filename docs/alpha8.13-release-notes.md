# KEMS 0.8.0-alpha8.13

Alpha8.13 is a coordinated Home Assistant + Web financial-parity release.

## One user-facing KEMS product

Normal users now see only **Live Data** and **KEMS**. The former Battery & Solar, Full KEMS and Full KEMS Agile names remain internal replay/validation evidence only. Existing installations retain their previous intent: Battery & Solar maps to no paid export, Full KEMS maps to fixed export, and Full KEMS Agile maps to Agile Outgoing.

KEMS exposes an **Export tariff** selector with three choices: no paid export, fixed/standard export and Agile Outgoing. That tariff selects the appropriate internal KEMS strategy while the product remains simply KEMS.

## Canonical household-bill total

Every user-facing financial comparison uses one versioned contract:

`electricity import + electricity standing charge - electricity export income - genuine supplier/account energy credits + gas usage + gas standing charge`

The headline is **Total energy cost**. Battery wear is deliberately excluded because it is not an item on the household energy bill. Battery-wear evidence remains available for engineering/economic analysis.

The contract publishes a breakdown for electricity import, electricity standing charge, export income, supplier/account credits, electricity total, gas usage, gas standing charge, gas total and overall total energy cost.

## Cross-surface parity

The managed Home Assistant dashboard and KEMS Web.4 consume the same `sensor.kems_energy_cost_comparison` payload. Web no longer reconstructs scenario cost from lower-level fields. If the canonical HA contract is unavailable, Web shows that the coordinated HA update is required rather than falling back to a different accounting formula.

## Coordinated versions

- KEMS Home Assistant / dashboard: `0.8.0-alpha8.13`
- KEMS Web / Pi / PWA / public site: `0.8.0-alpha8-web.4`
- ESP32 panel: unchanged at `0.8.0-alpha8-panel.1`

## Safety

This release changes reporting, product presentation and tariff-to-strategy selection. It does not enable physical control. Real FoxESS hardware writes remain blocked and the existing commissioning/control safety gates remain intact.
