# KEMS 0.8.0-alpha8.4

KEMS `0.8.0-alpha8.4` is a narrow Weekend Happy Hour migration/replay maintenance release.

The live 23 August test established an upgrade-specific gap: a Happy Hour completed under Alpha8.2 could reach Alpha8.3 with the planning switch disabled but without Alpha8.3's retained `last_completed` metadata. Without that record, the ordinary Agile day replay cannot include the already-completed free-charge window.

Alpha8.4 adds a conservative migration fallback. It reconstructs the completed-event metadata only when KEMS' durable Agile shadow audit proves both that `happy_hour_charge` ran inside the booked window and that a later non-Happy-Hour decision occurred at or after the booked end. It refuses to reconstruct a merely configured, cancelled, interrupted or otherwise ambiguous event.

This lets the existing Alpha8.3 Agile day-ledger replay remain the single accounting/SOC owner; the migration does not add a second Happy Hour overlay or a second SOC path.

All established Full KEMS Agile policy remains unchanged:

- battery charging still targets **100%**;
- the normal pre-cheap/export reserve remains **10%**;
- **23:30–05:30** remains the authoritative scheduled cheap house/battery charging window;
- extra Intelligent daytime slots do not automatically become house-battery cheap periods;
- overnight replacement cost remains the ordinary battery-export economic floor;
- highest-value feasible Agile export slots still win subject to forecast headroom, house/reserve, inverter, export-limit and deadline constraints;
- forecast headroom only re-times already-planned/exportable energy and does not create unnecessary battery cycling;
- Power Down remains higher priority than Happy Hour and normal Agile price dispatch.

KEMS Web / Pi / PWA remains `0.8.0-alpha8-web.1` (unchanged).

The ESP32 panel remains `0.8.0-alpha8-panel.0` (unchanged).

Real FoxESS hardware writes remain blocked. This release changes retained metadata/replay recovery only and does not commission or enable physical control.
