# Alpha9.248 — full-code audit follow-up (staged, not published)

**Recorded 21 November 2026.** This is a *development* checklist for [draft PR #536](https://github.com/kylejago/KEMS/pull/536), not an installation certificate. The booked Sunday 22 November Happy Hour must finish and physical normal-mode restoration must be independently established before approval, merging, publishing or any user-initiated installation. Keep the old release available during the event; do not trigger the normal 06:00–06:30 updater using a draft.

## Confirmed, directly actioned in alpha9.248

- **Release safety:** The publisher requires successful exact-main-SHA Validate (full test suite and ESPHome compile), HACS and hassfest checks, and rejects a stale main commit or a same-name release tag targeting a different commit. Publication only runs on `main` (or a separately authorised manual trigger); draft branch builds cannot expose the next release.
- **Happy Hour coordinator reload:** The per-config-entry auto-join cache is replaced for a new coordinator and cleared on unload, even in the presence of late old callbacks. Booking authority is not broadened.
- **Update safety:** Unknown/unavailable *current* off-peak binary now defers unattended maintenance. A removed legacy Intelligent binary is not treated as tariff authority. Existing planned-event, physical charging/export, EV and FoxESS restoration blockers are retained.
- **ROI provenance:** Audit rows distinguish independently supplier-awarded rewards, metered/modelled estimates, and event bookings with no valued credit; arithmetic remains unchanged.
- **Documentation/version checks:** Refresh the current operator/roadmap explanation and version-specific regression pins. Add a Python 3.14 syntax-only CI smoke check, while keeping the supported Python 3.13 full Home Assistant test suite.

## Verified already operating or already implemented: do not duplicate

- Site 7 kW DNO export limit, 15% deliberate-export target and 10% house-only battery floor; established accepted live evidence means there is no need to provoke unsafe repeat tests.
- Normal cheap import 23:30–05:30 and EV 5 kW Force Charge cap (with site headroom), without interpreting Ohme daytime charging as a supplier-confirmed whole-home cheap window.
- Backup-before-update **already defaults to enabled** and failed/unavailable `backup.create_automatic` is a hard stop; do not bypass it. Safe-first maintenance is 06:00–06:30 Europe/London.
- Paid Agile battery export is already live; `solar_routing_shadow` and its hardware pilot remain non-controlling.
- Happy Hour/Power Down precedence and normal Happy Hour behaviour already have accepted live and regression evidence.

## Not safe or not yet independently provable in this candidate

- **Solar-only mode switching (#365):** no new Feed-in First inverter writes without independent KH7 mode register observation, safe rollback, economic daylight proof, anti-flapping and a supervised physical test.
- **EV overnight handover (#498/#361):** requires post-23:30 live Ohme/FoxESS diagnostics; repository tests alone cannot prove physical restoration.
- **Historic gaps and Happy Hour cumulative meter (#487/#352):** require separately recent, independent and consistent meter readings; estimates cannot be promoted to real kWh or awarded credits.
- **Performance (#405):** previously improved to low single-digit scan seconds; continue to monitor multi-morning p95, not risk state/control mutation for speculative speed gain.
- **Exact duplicate modules:** The 21 November main Git tree contains **34 groups** of byte-identical Python files under `custom_components/kems`, totalling **461,221 repeated bytes**. These are primarily legacy alpha-named files paired with semantic-named runtime files; preserve them for now until imports, monkey patches and dynamic import compatibility have been independently audited. Their presence alone is not proof that an import or function is unused; deleting them now would pose an unjustified pre-event risk.

## Acceptance after the booked session

1. Check current diagnostic after the actual Happy Hour end: joined event finished, House/EV grid supply and FoxESS restored, no outstanding Force Charge, forced export, battery hold or restoration pending.
2. Ensure full latest PR head CI green (including ESPHome and the compatibility syntax check); audit any new CI failures rather than bypassing tests.
3. Recheck the latest main SHA and canonical manifest identity, then deliberately merge and let the publisher generate the verified tag/bundle after the event.
4. The HA update must still wait for its 06:00–06:30 local maintenance window and pass all safe-first energy checks; publication alone is not proof of installation.
