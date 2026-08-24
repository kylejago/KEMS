# KEMS 0.8.0-alpha8.10

Alpha8.10 is a coordinated shadow-runtime and cross-surface reconciliation release based on live KEMS evidence from 24 August 2026. It closes several places where individually correct Alpha8 layers could still disagree after composition: Full KEMS Agile dispatch, Power Down routing/accounting, incomplete future price horizons, commissioning tariff readiness and the Pi/Web comparison basis.

## Final Full KEMS Agile runtime reconciliation

- Selected Agile export slots are normalised with explicit half-hour start/end bounds so later event and deadline layers operate on the same settlement interval.
- A missing future Agile price no longer zeros a known, already-selected current export slot. KEMS keeps the known current decision and replans when the missing price publishes.
- If the current settlement price itself is unknown, the existing safety hold remains in force.
- Maximum-discharge/deadline reconciliation can no longer erase a non-zero export that the final selected current slot requires.
- The reconciliation layer is the final canonical Alpha8 compatibility boundary after dispatch reconciliation; Alpha8 does not start a new version-named runtime patch chain.

## Power Down route and accounting parity

- Active Power Down routing uses the current KEMS house load and enforces one net grid direction at a time; it does not present simultaneous planned import and export.
- The retained Power Down event ledger now follows the final Full KEMS Agile `current_routing_snapshot` instead of the generic proposal simulation when that canonical route is available.
- Planned battery-to-home energy, grid export and maximum inverter output are integrated from changing shadow targets through the event rather than multiplying one instantaneous sample by the whole session duration.
- Rewardable reduction uses the Octopus baseline against planned net site energy for the same interval.
- Ordinary fixed-export income remains separate from the Power Down reward and is not invented when the export tariff is unavailable.
- If the canonical Agile route is unavailable, KEMS keeps the existing simulation estimate rather than fabricating route evidence.

## Commissioning/readiness reconciliation

- A completed daytime `offpeak_end` value may be stale without making otherwise fresh tariff data fail commissioning readiness.
- Current import-rate availability and operational tariff freshness remain required; this does not weaken stale-data safety for live tariff decisions.

## KEMS Web / Pi comparison parity

Coordinated KEMS Web version: `0.8.0-alpha8-web.3`.

- Compare uses import cost minus export income as the common winner basis.
- Standing charge, battery-wear assumptions and Power Down reward are excluded from strategy winner ranking.
- While the physical system is uninstalled, Live Data uses the canonical KEMS rolling no-system replay for the selected period so the comparison is coherent.
- After installation, mismatched Live-period evidence remains unavailable instead of comparing unlike periods or scaling shorter evidence.
- The property website remains read-only.

## Unchanged coordinated components and safety

- managed ESP32 panel: `0.8.0-alpha8-panel.1` (unchanged)
- automatic Octopus Weekend Happy Hour discovery/retention remains enabled with its fail-safe/manual fallback behaviour
- selectable EV charging policy remains shadow-only
- priority remains Safety > Power Down > Happy Hour > permitted EV > normal Agile
- no Home Assistant service call to Octopus or Ohme is added
- no FoxESS hardware write is added
- no public EV state, SoC, charging times or identifiers are exposed

Real hardware writes remain blocked.
