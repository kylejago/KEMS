# KEMS 0.8.0-alpha8.12

Alpha8.12 is a narrow Home Assistant/dashboard cleanup release following the proven Alpha8.11 startup hotfix.

## Managed dashboard hardening

The managed Updates card previously read optional attributes with direct Jinja attribute access:

`update.attributes.last_error` / `maintenance.attributes.error`

Home Assistant can omit those attributes when there is no failure, which produced a non-fatal dashboard `UndefinedError`. Alpha8.12 keeps the packaged dashboard source compatible while the managed-dashboard rendering pass rewrites that expression to safe `.get(...)` access before KEMS installs the dashboard.

## Release metadata cleanup

The coordinated bundle now describes the actual maintenance scope for this release: KEMS Home Assistant core plus the managed dashboard. Unchanged Web and panel components are no longer listed as affected merely because they remain present in the coordinated bundle.

## Coordinated versions

- KEMS Home Assistant / managed dashboard: `0.8.0-alpha8.12`
- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.3` (unchanged)
- ESP32 managed panel: `0.8.0-alpha8-panel.1` (unchanged)

## Scope and safety

No Agile, Power Down, Happy Hour, EV-policy, forecasting, simulation, accounting, or physical-control behaviour is intentionally changed by Alpha8.12.

The Alpha8.11 startup fix remains intact. Real hardware writes remain blocked and KEMS remains simulation/shadow only.
