# KEMS 0.8.0-alpha8.6

Alpha8.6 is an install-blocking Home Assistant/dashboard hotfix for Alpha8.5. It does not change the EV charging policy, Pi/Web release, managed panel firmware, Agile optimiser, ledger, dispatch or hardware-write boundary.

## Fixed

- The Alpha8.5 EV dashboard transform looked for a `Current routing and today totals` card marker that is not part of the consolidated Full KEMS Agile dashboard. On Home Assistant restart this raised `ValueError: Full KEMS Agile routing card marker missing` and prevented the KEMS config entry from setting up.
- The EV policy cards now insert at the stable consolidated `Full KEMS Agile` view boundary (`full-kems-agile`).
- Regression coverage now runs the EV insertion against the real dashboard consolidation renderer rather than a synthetic card marker.
- If a future dashboard refactor removes the expected Full KEMS Agile view, the EV presentation is skipped with a warning instead of raising an exception.
- KEMS setup now also treats a managed-dashboard `ValueError` as non-fatal, so a presentation transform cannot stop the coordinator, recorder or shadow engine from starting.

## Unchanged coordinated components

- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.2` (unchanged)
- managed ESP32 panel: `0.8.0-alpha8-panel.1` (unchanged)
- default EV policy remains **EV cheap-window mode**, permitting EV charging only in the authoritative **23:30–05:30** overnight window
- Power Down remains higher priority
- battery discharge/export isolation around allowed or still-observed blocked EV charging is unchanged
- no Home Assistant service call to Ohme is added
- no FoxESS hardware write is added

Real hardware writes remain blocked.
