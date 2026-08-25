# KEMS Alpha8.14 — dashboard verification and Live Data / KEMS presentation

Alpha8.14 is a narrow Home Assistant release on top of the proven Alpha8.13 bill-equivalent financial contract.

## Updater repair

The coordinated updater now repairs the KEMS-managed dashboard during post-restart verification when the dashboard is missing or stale. Verification still waits until the coordinated release bundle has been rediscovered after restart. Once the bundle is available, KEMS rebuilds the managed dashboard from the running release before the normal component verification decides whether the transaction can complete.

This prevents a healthy core update from remaining indefinitely in `verifying` only because the dashboard component reports `installed: null` / `waiting`.

The dashboard verifier continues to compare `/config/kems_master_dashboard.yaml` against the exact combined runtime payload: master dashboard + retained advanced strategy views + the direct update-check button.

## Dashboard product presentation

The normal managed-dashboard journey is now organised around the two user-facing choices introduced in Alpha8.13:

1. **Live Data vs KEMS** — headline status, today's total energy cost and saving.
2. **Live Data** — what the home and supplier account actually did.
3. **KEMS** — the result of the KEMS-selected internal strategy for the configured tariff/system.
4. **Compare** — canonical Live Data vs KEMS totals and bill breakdown across reporting periods.

Legacy simulation engines remain present for engineering evidence, commissioning, validation and regression, but their tabs are explicitly labelled as engineering/advanced views rather than separate products.

## Financial contract unchanged

Alpha8.14 does not redesign the Alpha8.13 financial model. Headline total energy cost remains:

- electricity import cost
- plus electricity standing charge
- minus electricity export income
- minus genuine supplier/account energy credits
- plus gas usage cost
- plus gas standing charge

Battery wear and modelling adjustments remain excluded from the headline household bill comparison.

## Coordinated component versions

- Home Assistant / KEMS core: `0.8.0-alpha8.14`
- Managed dashboard: `0.8.0-alpha8.14`
- KEMS Web / Pi / PWA / public: `0.8.0-alpha8-web.4`
- ESP32 panel: `0.8.0-alpha8-panel.1`

No physical-control permissions are changed by this release.