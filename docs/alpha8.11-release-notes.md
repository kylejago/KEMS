# KEMS 0.8.0-alpha8.11

Alpha8.11 is a narrowly scoped Home Assistant startup hotfix for the Alpha8.10 reconciliation release.

## Home Assistant startup recovery

A real Alpha8.10 installation exposed a circular import during Home Assistant startup:

`coordinator -> agile_smart_export_runtime -> agile_runtime_reconciliation -> commissioning -> entity -> coordinator`

`KEMSEntity` only needs `KEMSCoordinator` for typing, so Alpha8.11 moves that coordinator import behind `TYPE_CHECKING` and removes the runtime dependency. This allows the coordinator and Alpha8.10 reconciliation layer to initialise normally.

## Coordinated versions

- KEMS Home Assistant: `0.8.0-alpha8.11`
- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.3` (unchanged)
- ESP32 managed panel: `0.8.0-alpha8-panel.1` (unchanged)

## Scope and safety

No Agile, Power Down, Happy Hour, EV-policy, simulation, accounting, or physical-control behaviour is intentionally changed by this hotfix.

The Alpha8.10 reconciliation behaviour remains intact and real hardware writes remain blocked. KEMS remains simulation/shadow only; no real Ohme or FoxESS control is enabled.
