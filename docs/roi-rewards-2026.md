# ROI reward recognition and verification

From alpha9.176, KEMS actual ROI includes (1) ordinary avoided day-rate import and Agile export income as before, (2) distinct individually completed, meter-backed Weekend Happy Hour credit *estimates* and (3) a modelled extra Power Down bonus **only** when positive rewardable reduction, positive bonus, completed session and physical export verification are all available.

The extra Power Down bonus excludes the ordinary Agile export income already recorded in the physical financial ledger. Happy Hour credit is never subtracted a second time from gross import. Per-event IDs and exact one-hour booking windows are journalled independently across coordinator scans and Home Assistant restarts.

**Supplier verification:** Booking or metering confirmation is not proof of Octopus payment. The BottlecapDave integration does not currently provide per-event settled Happy Hour bill credits or confirmed Power Down Octopoints amounts to KEMS. Accordingly these reward contributions are labelled unsettled and must not cause a permanent payback-date transition. If the supplier bonus cannot be evidenced or valued, it contributes no additional estimated ROI until it can.

In the 3 November 2026 diagnostic, the completed 1 November 12:00-13:00 Happy Hour hour has an estimated £2.61729 refund. The second hour has insufficient meter evidence. Power Down session 8135 has 3.268 kWh physically verified export (already counted in normal Agile earnings) but no confirmed bonus amount: extra Power Down ROI is still pending.

The original lifetime financial ledger and gross electricity bill are deliberately untouched by this ROI-only overlay; the dedicated three reward sensors explain the difference between base ledger value and presented ROI value.
