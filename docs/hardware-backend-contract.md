# KEMS hardware backend contract

KEMS must keep energy policy, optimisation, safety validation and vendor-specific inverter writes as separate layers.

The existing `ControlEngine` is intentionally hardware-independent. Its `ControlState` is the vendor-neutral desired-command contract: work mode, charge power, battery-to-home power, battery export power, total discharge power, minimum SOC, EV permission, grid-export permission and safety/commissioning state are calculated before any hardware adapter is allowed to act.

## Backend boundary

A future live hardware backend must translate a validated KEMS command into the smallest supported vendor-specific write set. It must not re-plan prices, reserves, export timing or EPS policy inside the vendor adapter.

Each backend must provide or normalise these observations where the hardware exposes them:

- battery SOC and battery power/direction
- solar/PV power
- house/load power
- grid import and grid export as non-negative magnitudes
- inverter/work mode
- charge/discharge limits and relevant minimum-SOC settings
- grid/island/EPS availability where supported
- freshness/availability evidence for every value used for control

Each writable backend must explicitly declare support for the KEMS command capabilities it can safely implement. Unsupported commands fail closed rather than being approximated silently.

## Write safety

Before a real write is permitted, the shared KEMS commissioning and shadow gates remain authoritative. The adapter must not bypass `ControlState`, the independent shadow validator, the configured inverter/export limits, minimum SOC, stale-data protection, emergency stop, or the system-commissioned flag.

Writes should be idempotent and read back where the vendor exposes a confirmation entity. A failed or ambiguous write returns the backend to a safe local/self-use state and reports the reason to KEMS.

## FoxESS first

FoxESS is the first live-control backend. Its commissioning will establish the proven mapping between vendor entities/registers and this contract. That gives us real evidence for mode transitions, write ordering, readback timing and safe failure behaviour rather than guessing those semantics in advance.

## Alpha ESS next

Mike's Alpha ESS system should use the same planner, Agile logic, forecast logic, safety rules, dashboards and update framework. Only the observation normalisation and command translation belong in an Alpha ESS backend.

Do not implement Alpha ESS writes before FoxESS live control is proven. Before then, prep is limited to preserving this vendor-neutral boundary and collecting the exact Alpha ESS model, Home Assistant integration/entity set and supported control operations when Mike's hardware is available.

This avoids a FoxESS-shaped KEMS core and avoids maintaining two separate energy-management systems.
