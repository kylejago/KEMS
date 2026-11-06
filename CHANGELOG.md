## 0.9.0-alpha9.187 — Verified EV restart floor and lower-overhead Agile publication

- **Connected EV restart protection:** During a positively confirmed cheap/Intelligent period, pre-arm a FoxESS Min SoC (On Grid) at or above the observed battery SOC (with a 1pp bounded margin) before switching a connected idle EV from Force Charge to Self Use. Require the physical MinSOC readback before mode handover; if it cannot be verified, retain the existing work mode and retry on a later scan, without restoring a low baseline.
- **Scope:** Do not alter the separately opted-in paused-Ohme household-only bridge outside cheap periods, 15% deliberate paid-export cutoff, 10% household floor, 7kW DNO limit, Power Down or Happy Hour precedence. Software coordination and periodic scans are not an electrical EV interlock; the transition safeguard still needs KH7 live validation.
- **Agile performance:** In the coordinator only, defer one redundant initial read-only Agile presentation cascade until the guaranteed authoritative same-scan settlement publication. All historical exact-input SHA-256 checks, current-day numerical comparisons, forecast inputs, physical control, settlement and state data continue to run; standalone manager calls still publish immediately. Instrument the deferral and verify scan speed after installation.
- **Display and price evidence:** Rename Live Data battery labels as measured FoxESS SOC, preserve the explicit advisory simulation comparison, and state that missing Agile half-hours remain unknown without inferred values.
- **Testing and rollout:** Add regression tests for the cheap handover guard, failure boundary, scoped publication and UI semantics. Retain safe-first 06:00–06:30 update installation only when not actively exporting.

## 0.9.0-alpha9.186 — Verified paused Ohme enables optional 10% household-only reserve

- Add a **separate, default-off** `ohme_idle_house_bridge_enabled` control option because this introduces a new explicit Ohme mode write outside the Happy Hour reward session. With the option enabled, KEMS may pause the uniquely reviewed Ohme ePod near the 15% export reserve while paid Agile export is idle and the EV is physically connected but not drawing power.
- Require the actual Ohme mode to read back **Paused**, with two distinct fresh zero-power reports, before lowering FoxESS Min SoC (On Grid) to **10% for household Self Use only**. Ordinary 'plugged in, 0 kW' never authorises the lower floor. Existing 15% deliberate export cut-off, staged export proof, Happy Hour and Power Down authority are unchanged.
- Before resuming KEMS-owned Ohme Smart charge, require physical readback of a protective FoxESS Min SoC value at or above current battery SOC and at least 15%. Store pause ownership before writing so a restart never forgets it. A safety fault leaves the charger paused rather than exposing the battery; restoration waits for proof.
- This is a **software-coordinated pause**, not electrical isolation: an external Ohme user or app can override it between scans. It must not be claimed as absolute anti-discharge protection without an independently verified hardware interlock. Confirm the physical behaviour on the live KH7 before relying on it.

## 0.9.0-alpha9.185 — Reviewed FoxESS Modbus 1.16.0 KH7 control compatibility

- Restore the commissioned KH7 control backend after FoxESS Modbus updated from 1.15.0 to 1.16.0: explicitly allow **only** the two reviewed upstream versions; missing and unreviewed versions continue to fail closed. Keep the original latest-reviewed-version diagnostic key and add the full version allowlist so compatibility decisions are auditable.
- Upstream 1.16.0 review: KH remote-control register and power-setpoint mapping remains unchanged; the remote-control manager adds an overlapping-update guard. The changed H3 inverter-battery-power register in 1.16.0 is **H3-only**, not the KH7 mapping. Keep KEMS command binding, physical readback, 1 kW first-export staging, independent battery/grid proof and three-strike safety logic unchanged.
- Preserve all other authority gates, including explicit Agile paid-export selection, reviewed 7 kW export-power-limit readback, 15% paid-export reserve, 10% absolute home battery floor, EV battery-drain protection, Happy Hour no-discharge, Power Down rewards and the automatic 06:00–06:30 safe update window with no installation during export.
- Add exact-version regression coverage (including absent/future versions) and version-to-backend gating checks. Source review and CI do **not** substitute for an on-device staged live-control confirmation after installation.

## 0.9.0-alpha9.184 — Agile reporting efficiency and auditable financial/telemetry evidence

- Suppress exact duplicate state-and-attribute Home Assistant writes **only in the initial read-only Agile comparison publication**. Continue immediately publishing changed price, SOC, tariff, plan and reporting attributes; retain synchronous settlement, final deadline, direct-call and control update behaviour. Record initial writes and suppressed duplicates for subsequent field timing checks.
- Explicitly flag reported physical export income alongside zero displayed current-day export kWh without modifying either actual measured value or replay ledger; further source/interval reconciliation remains evidence-gated.
- Explain old FoxESS sensor report timestamps corroborated by fresh numeric siblings on the *same registered Modbus device*, versus genuinely rejected stale fields. Do not weaken original freshness, commissioning or proof checks.
- Clearly separate ROI-included provisional partial Happy Hour credit, completed meter-supported estimates and supplier-confirmed settlement; none is represented as paid without source confirmation. Normal Agile Power Down export is never counted twice.
- Add regression coverage for unchanged/changed initial publication, settlement and direct publisher preservation, lookup fail-open, source corroboration and reward provenance.
- No changes to physical FoxESS writes, Ohme EV charging, 7 kW DNO export limit, 15% deliberate export reserve, 10% absolute household floor, Happy Hour/Power Down authority, or 06:00–06:30 safe-first update window with installation blocked during active export.

## 0.9.0-alpha9.183 — Overnight coordinator and ROI reporting stability

- Coalesce a redundant final-deadline Agile flow publication while preserving settled-SOC first publication, same-scan continuity and mandatory final publication; instrument coordinator wall-clock vs thread CPU time for slow scan attribution.
- Fix nullable reward audit fields in ROI dashboards and clarify cheap charging display after the slot becomes active; retain historic-adjustment-aware lifetime house/whole-home total state classes.
- Keep all FoxESS, EV, event, export-limit and battery safety rules unchanged.

## 0.9.0-alpha9.182 — Maintain physical paid-export proof through temporary house-demand absorption

- After the first valid 1 kW incremental Force Discharge sample, retain that **verified** battery-discharge-plus-grid-export observation for at most 180 seconds if subsequent solar-safe samples merely show that the household consumed the export headroom. This is inconclusive, not a physical hardware failure.
- Promote full bounded export **only after two distinct physical sensor publications** (fresh battery and grid-export reports) with independently verified active Force Discharge, correctly bound 7 kW hardware export ceiling and positive net grid export. Repeated coordinator scans of the same physical reading do not count.
- Reset a partial sample after mode exit, unsuccessful command, expired window, CT/inverter disagreement, solar-only export or real hardware failure. Preserve three real failure strikes, the 1 kW staging ceiling, session-scoped proof (never persisted/reused across restart), commissioned limits and all EV/reward control.
- Add regression tests reproducing the 4 Nov 18:31 2.009 kW Force Discharge vs 2.492 kW household load, duplicate reports, expiry, mode exit and wrong export-limit readback. No extra scans, background tasks or reporting load.

## 0.9.0-alpha9.181 — Reduce redundant synchronous Agile settlement reporting

- Coalesce the intermediate Canonical Flow publication **only** while the enclosing Deadline Settlement owner guarantees a complete, synchronous final publish after the same-scan canonical, solar and deadline overlays. Direct Canonical and Solar callers still publish normally.
- Keep the mandatory first settled-SOC/price/rolling-control publication, the Flow owner publication, every reconciliation calculation, and the final Deadline publication intact. No asynchronous queue, new cache, stale-state shortcut or disabled SOC continuity.
- Expose `deferred_canonical_flow_publications` in the existing per-scan publication coalescing diagnostics. The pre-upgrade reference was 4 underlying Agile publication passes consuming 1.254 seconds (6.713-second scan); assess measured improvement only after the new release runs in HA.
- Test direct callers, same-scan corrected SOC/price/solar/deadline states, exception flag cleanup, and unmodified coordinator/control boundary. Preserve FoxESS/Ohme write authority, 7 kW export cap, 15% paid-export floor, 10% household minimum, Power Down/Happy Hour reward accounting and 06:00–06:30 no-active-export auto-install gate.
- Require exact-commit Black, Ruff, full pytest, Python compilation, HACS/Hassfest and ESPHome panel compile.

## 0.9.0-alpha9.180 — Commissioned reward-history recovery and true EV SOC display

- Scan the independently joined Octopus Weekend Happy Hour feed back to the configured financial commissioning date **for financial evidence only**; the existing seven-day live booking/charging authority is unchanged. Persist each historical joined one-hour booking identity in the dedicated ROI journal so it remains auditable after the upstream feed expires.
- Value old Happy Hour hours provisionally **only where retained five-minute KEMS grid-import snapshots and their captured historical import prices cover witnessed intervals**, with a maximum 390-second adjacent sample gap. Missing minutes, tariff gaps, unconfirmed bookings and periods without samples remain pending. Label these estimates as lower-confidence than the dedicated physical-meter hour receipts; do not invent meter readings or mark supplier settlement complete.
- Show known-hour and known-Power-Down-event coverage, included versus pending evidence, and explicitly that supplier history discovery may be incomplete. Older Power Down events without independent bonus/baseline proof remain pending; regular Agile export is never double-counted.
- Prefer the **fresh vehicle-integration SOC** for the displayed KEMS EV battery percentage (for example 83% over a stale unplugged Ohme 99%). Fall back to Ohme for unavailable or stale vehicle observations; physical EV charging authority, snapshot, Ohme write cadence and plugged/charging guards are unchanged.
- Keep historical backfill memoised per completed joined-hour identity to avoid repeated whole-history scans in the fast coordinator; existing Agile publication timing remains instrumented. Do not claim a measured fix to the separate synchronous settlement publication bottleneck without a safe behavioural proof.
- No changes to live FoxESS writes, Power Down/Happy Hour dispatch, 7 kW DNO limit, 15% paid export reserve, 10% household hard floor, EV battery protection or the 06:00–06:30 safe-first installation gate. Gate release on full validation.

## 0.9.0-alpha9.179 — Reconciled reward evidence and restart/performance observability

- Reconcile the completed-hour Happy Hour financial receipts with separately recorded, partially witnessed ROI estimates by exact independent one-hour booking boundaries. Show the complete-hour and provisional tiers, their differences, coverage, and rate evidence together in diagnostics; a partial estimate never becomes a verified receipt and neither proves supplier settlement. No extra credit or missing meter samples are invented.
- Add bounded per-layer settlement publication timing counters for the restart SOC anchor and underlying Agile reporting chain. Retain each original synchronously sequenced SOC, tariff, shadow and publish calculation; this **measures** the remaining bottleneck and does not promise a speed-up until field timings support a safe optimization.
- Observe future Home Assistant `homeassistant.restart` service calls via a read-only bus listener, exposing only the timestamp and whether user/parent context exists. Never log identifiers, service arguments, or infer who initiated a restart. Existing November 4 09:44 request remains unattributed.
- No changes to FoxESS write authority, EV hold/SOC sync, Agile price recovery, Power Down control, Happy Hour booking or charging, 7 kW export ceiling, 15% paid-export cut-off, 10% home-use floor, or safe-first 06:00–06:30 no-active-export installation window.
- Gate merge/publication on exact-commit Black, Ruff, full pytest, Python compile, HACS/Hassfest and ESPHome panel compile.

## 0.9.0-alpha9.178 — Provisional reward earnings until confirmed

- Add *provisional* Happy Hour bill-credit estimates for individually Octopus-confirmed reward hours with physically witnessed but incomplete grid-import coverage. Integrate only observed meter intervals no more than three minutes apart; never invent missing meter samples, extrapolate to the entire hour, or exceed 16 kWh per hour.
- Persist the observed import tariff along with newly captured Happy Hour physical meter samples. For legacy samples without saved tariff, permit an explicitly low-confidence, **adjacent completed verified-hour indicative rate proxy**. Without metered energy or a defensible rate, the amount remains pending.
- Credit the provisional partial-hour value to actual ROI under the same unique hour key. Once a completed hour receipt becomes available, replace its provisional value rather than counting two amounts. Both stages remain Octopus-unsettled pending supplier proof.
- Show provisional and meter-supported reward totals separately in ROI sensors and dashboard, with event-level meter coverage, tariff basis, confidence and evidence in the audit.
- Show modelled normal Agile export income alongside each Power Down event as context. It was already counted in the base physical ROI and is **never added a second time**. Any extra Power Down bonus requires event-specific reward-rate and reduction evidence; unknown extra awards remain unknown, not imagined.
- No changes to Happy Hour join authority, Power Down dispatch, FoxESS live control, 7 kW grid export ceiling, 15% intentional export cut-off, 10% house floor, EV protection or 06:00–06:30 no-export update policy.

## 0.9.0-alpha9.177 — Itemised ROI reward provenance and supplier-settlement audit

- Explain every Happy Hour and Power Down reward included in actual ROI using the existing persisted event-level reward journal, with event ID where independently known, original date/window, estimated value and evidence source.
- Correlate Happy Hour receipts against independently confirmed Octopus joined bookings by exact one-hour boundaries. The verified 1 November 12:00–13:00 hour can show joined event 8067; the second hour (8068) remains pending rather than fabricating a credit.
- Show completed Power Down events with missing bonus or baseline as pending. The 3 November session 8135 has physically verified export but no separately established reward amount, so its Agile export remains counted normally and no bonus is invented.
- Expose a bounded, read-only reward audit via `sensor.kems_roi_reward_audit`, the ROI dashboard and diagnostics, including the source of existing historical bonus estimates such as the previously opaque £0.56.
- Preserve 9.176 financial totals and reward idempotency; no changes to the physical energy ledger, Octopus booking, FoxESS commands, 7 kW DNO limit, 15% deliberate export cut-off, 10% household floor, EV battery protection or 06:00–06:30 no-export update policy.

## 0.9.0-alpha9.176 — Reward-inclusive actual ROI, with supplier-settlement provenance

- Count completed, individually verified Happy Hour import bill-credit estimates toward displayed actual ROI from the financial commissioning date. Preserve the original gross metered bill and historical tariff rate. A supplier credit is **not** marked settled until Octopus confirms it.
- Count the **additional** Power Down reward only when a positive modelled bonus amount, rewardable reduction and successfully completed physically verified event are all available. Normal Agile export earnings are already included and must never be added twice. Missing bonus/baseline remains unknown, not £0 earned.
- Persist the once-per-event reward journal across restart and history retention independently of inverter control. Show separate Happy Hour and Power Down ROI estimates and an unsettled-rewards total on the ROI dashboard.
- Apply a read-only ROI overlay rather than rewriting metered energy, physical daily import/export figures or historical value fields. Estimated rewards cannot mark permanent supplier payback complete.
- No change to Octopus booking authorisation, FoxESS write authority, 7 kW grid-export limit, 15% deliberate-export target, guarded 10% household minimum, EV charging protections or 06:00–06:30 no-export maintenance gate.

## 0.9.0-alpha9.175 — Weekend Happy Hours variable-token and booking evidence (candidate)

- Read the genuine Octopus GraphQL Weekend Happy Hours token balance from the unique account coordinator, irrespective of the presence of the public Power Up event entity. The upstream public sensor's balance / 2 is labelled a legacy estimate, **not** guaranteed hours. The token price per event is unknown; Octopus remains booking/eligibility authority.
- Preserve night-before (Saturday or Sunday) selection with verified import/export Agile price coverage. Enforce a **single two-hour allowance per weekend**, not two separate daily allowances. Retain Saturday joined-event evidence when considering Sunday booking eligibility.
- A successful booking-service response becomes a pending acknowledgment. Do not make a second booking, authorise live Happy Hour free import, or add a financial receipt until the independently joined Power Up event feed confirms the booked hour. Preserve idempotency and expose the pending state; rejected bookings remain failures with a cooldown.
- Correct the **read-only** FoxESS Force Discharge shadow parity to compare the total setpoint (house support plus grid export) against the total live command, rather than comparing grid-only export with total discharge. Add explicit no-hardware-write parity regression coverage; actual FoxESS dispatch is not changed.
- Include behavioural regression tests for raw tokens, misleading /2 legacy figures, ambiguous source rejection, weekend cap and acknowledgment-versus-joined-event authority. Preserve the 9.173 verified actual-import estimated-credit ledger; do not fabricate missing November 1 meter evidence or Octopus supplier settlement.
- **Release gate:** full pytest, Ruff, Black, HACS/Hassfest and ESPHome CI must pass before merging; deployment only in the configured 06:00–06:30 no-active-export maintenance window. Power Down, 7 kW export ceiling, 15% deliberate export target, guarded 10% house minimum and EV discharge protections unchanged.

## 0.9.0-alpha9.174 — weather resilience and independent shadow reserve parity (candidate)

- Defer one read-only Solar continuity settlement publication *only* when the outer Deadline owner guarantees the same-scan final publish after both solar and deadline enrichment; direct Solar callers publish immediately, and the defer flag always resets on error. Add AST-backed behavioural tests for direct publication, combined fields and exception cleanup. This targets one redundant heavy pass, not the entire P1 #405 bottleneck; verify actual timing on the next overnight diagnostic.

- Correct the read-only shadow command validation mismatch: no deliberate export can use the guarded 10% household SOC floor, while paid battery export still requires the configured 15% reserve, and island protection retains the separate island reserve. No changes to physical FoxESS commands or the live control gate.
- Exponentially back off Open-Meteo outages (5, 10, 20, 40, then 60 minutes), reduce repeated log floods and retain only same-day, at-most-six-hour-old cached weather evidence; beyond that KEMS falls back to other available forecast sources rather than treating stale Open-Meteo as fresh.
- Retry a transient DNS/connection failure once during read-only GitHub release metadata discovery. HTTP errors, release verification, checksum and all safe-first installation protections remain unchanged.
- Add isolated behavioural tests for weather backoff/cache age and independent shadow reserve constraints. **Pending full CI and release review.**
- The 1 November missing Happy Hour second-hour credit cannot be certified from the saved 13:48-last-meter-sample and grouped booking: do not invent import, independent booking or supplier refund. Performance issue #405 and hardware proof issues #349/#352 remain independently open pending measured fixes/physical evidence.
- Preserve 7 kW export cap, 15% paid-export cutoff, guarded 10% verified-unplugged household self-use, no battery discharge into EV, Power Down and active Happy Hour authority, and 06:00–06:30 no-export updates.

## 0.9.0-alpha9.173 — consistent Happy Hour bill estimates and missing-proof diagnostics

- Fix Live Data and History displaying gross Happy Hour import costs as if no refund existed: calculate estimated credited kWh/credit and effective electricity import, electricity and full energy cost separately for every retained period. Main Home costs, daily card, 7 history periods and generated Energy Cost cards use the same canonical financial fields.
- Keep gross day-rate grid-import charges, original tariff history, standing charge and export earnings untouched. Octopus's later Happy Hour account credit is **estimated and unsettled**, not an already-paid refund or a literal 0p supplier import rate. Historical credit is never repriced using today's import rate; period aggregation uses persisted dated verified reward receipts.
- Preserve gross-basis Live Data vs KEMS savings comparisons to avoid presenting unlike bases as measured optimisation; show effective Live totals separately and label the estimated credit explicitly.
- Add bounded read-only per-window diagnostics with statuses for saved verified receipts, genuinely independently booked hour without complete meter/tariff proof, and legacy grouped sessions that do not prove separate rewards. The 1 Nov second-hour 13:00–14:00 gap is **not** fabricated, interpolated or marked settled; issue #419 remains open.
- No change to EV or FoxESS control, physical 7 kW export limit, paid 15% battery cutoff, guarded 10% household self-use, Power Down, Happy Hour physical import permissions or 06:00–06:30 no-active-export safe updates. Full CI required before auto publication.

## 0.9.0-alpha9.172 — durable independent Happy Hour accounting confirmations

- Persist each genuinely confirmed one-hour Octopus joined reward (including its event ID/code and source) immediately, even if the physical grid import meter is temporarily stale or unavailable. Adjacent two-hour dispatch/display groups are no longer submitted to the financial evidence recorder as independent booking proof.
- Keep one 16 kWh allowance per individually authorised hour; no pooled allowance, duplicate credits, or fabricated missing meter samples. Save confirmation provenance and physical import observations independently; retain both across normal Home Assistant restarts and disappearing joined-event feeds.
- Historical Sunday 1 November 2026 figures are reconstructed **only where independently evidenced** by saved booking and complete physical tariff/meter history. The observed two-hour total (10.949 kWh; 392.881p indicative credit) is not automatically written back if the stored second-hour meter trail ends at 13:48. Credit reporting remains read-only and does not change gross import, supplier settlement or physical control.
- Add automated tests for adjacent bookings, rejection of merged two-hour evidence, stale meter confirmation, restart retention, and storage failures. Preserve 7 kW DNO export limit, 15% paid-export cutoff, guarded 10% confirmed-unplugged household Self Use, EV discharge prevention, and the 06:00–06:30 safe-first update window.

## 0.9.0-alpha9.171 — synchronous Tomorrow publication consolidation and guarded household SOC floor

- Remove an intermediate heavy Tomorrow handoff publication only when its calling FlowPresentation manager guarantees the final canonical flow is published before the same synchronous settlement reconciliation returns. The first pre-control SOC/price publication remains mandatory, changed Tomorrow data still reaches Home Assistant in the same scan, and direct handoff callers still publish independently. The latest diagnostics showed ~0.6 seconds per intermediate publication; verify actual reduction after installation.
- Permit physically configured FoxESS MinSOC 10% solely for ordinary paid-export idle Self Use with externally verified Ohme unplugged status, confirmed noncharging and zero EV power, no Power Down/Happy Hour/Intelligent hold, no stale EV grace and hardware number minimum allowing 10%. Paid battery-export cutoff remains 15%, and EV-connected, charging, unknown/unavailable and force-discharge paths retain existing minimums. This does not change commissioning/baseline restoration or bypass inverter safety.
- Preserve 7 kW DNO, evidence-only Happy Hour accounting, EV battery protection and safe-first 06:00–06:30 no-export auto-update. Sunday 1 November second-hour credit remains unverified.
- Compare the actual overnight 03:00–07:45 performance after installation rather than claiming this ends all slow scans.

## 0.9.0-alpha9.170 — lower Agile state-write load and correct all-time Happy Hour credit

- Coalesce *any* byte-for-byte unchanged Agile Home Assistant entity state and attributes inside the existing synchronous pre-control settlement scope, including the first publication of an entity. New or changed same-scan tariff, SOC, Tomorrow handoff and flow data publish immediately. HA lookup/comparison errors fail open to the original write. No cache, no altered async boundary, and no physical inverter control changes. New counters separately show first-pass unchanged suppressions so performance improvement is measurable against alpha9.169.
- Correct lifetime/all-time Happy Hour estimated credit and eligible import to sum previously persisted daily financial rows and the live tracking day, exactly once. The all-time report previously showed 0p while November/year/financial showed 261.729p from 7.294 kWh. Preserve original gross import and supplier-settlement status.
- Do not invent the missing 1 November 13:00–14:00 second-hour credit: independent booking and physical meter coverage remain incomplete in available on-device records. Issue #419 remains open.
- Preserve 7 kW DNO grid export limit, 15% paid-export cutoff, 10% household hard protection, EV connected-idle export, Power Down and Happy Hour controls. Automatic safe-first updates remain 06:00–06:30 and avoid active export. Validate the next 03:00–07:45 slowdown separately; no unmeasured improvement claim.

## 0.9.0-alpha9.169 — Happy Hour booking proof and safe updater checks

- Preserve independently confirmed one-hour Happy Hour reward windows before adjacent booked sessions are grouped for display. Capture physical meter samples up to ten minutes beyond the confirmed end, **for financial evidence only**, never live charging authorisation.
- Add exactly one retry for transient GitHub asset timeouts and HTTP 500, 502, 503 and 504; reject invalid checksums, version mismatches, wrong media types or 4xx without retry. Continue to install only in the existing 06:00–06:30 safe-first window and never during active export.
- Add bounded publication pass count, measured Agile publisher wall/CPU time to settlement diagnostics. No phase, async boundary, inverter control, same-scan publication or safety logic changed. **Early-morning slow scans are still under investigation (#405); this is instrumentation, not a claimed performance fix.**
- The Nov 1 second-hour refund is still not independently recoverable from the existing merged booking evidence and partial physical coverage. Preserve the verified first hour; investigate #419 without inventing import or booked sessions.
- Preserve 7 kW DNO export limit, 15% paid-export cutoff, 10% household floor, EV connected-idle export, Happy Hour and Power Down controls.

## 0.9.0-alpha9.168 — historical Happy Hour refund recovery after restart

- Fix the second observed 1 November regression: the independently verified physical meter recorder pruned completed reward-hour windows and samples only six hours after the event. The earlier proof was removed from memory before Alpha9.167 could persist the first-hour financial receipt.
- Retain the confirmed physical reward-hour timeline for seven days (bounded to 1,500 samples) across normal Home Assistant restarts. Existing storage path and schema remain unchanged so the previously saved meter data can potentially be rehydrated during the next safe update.
- Reconstruct **completed one-hour reward receipts only** from independently confirmed persisted windows, *complete measured* physical import coverage, and consistent historical KEMS import tariff readings from the original hour. Do not reprice yesterday's Happy Hour using today's 6.6p/kWh cheap rate, extrapolate missing meter intervals, or treat publicly advertised events as booking proof.
- Preserve recovered receipts across subsequent days and attribute historic reward credit to the original day's existing bill-equivalent ledger (not tomorrow's usage). Leave gross import, export, gas and supplier-settled status untouched. If old storage or historical tariff evidence is missing, mark recovery incomplete rather than invent a payment.
- Record physical ledger load status and configured retention days for diagnostic verification. New tests cover morning restoration, independent hour caps, mixed or missing tariff evidence, missed meter samples, source rebinding and seven-day expiry.
- **Physical safety unchanged:** no modification to FoxESS writes, charging, EV policy, export planning, DNO 7 kW limit, 15% paid-export cutoff, 10% household floor, Power Down or Happy Hour live authorisation. Simulated SOC differs from physical SOC by design; read-only reporting needs separate review.
- Publish only after pytest, Black, Ruff, HACS, hassfest and ESPHome validation. Auto installation must be deferred to the configured **06:00–06:30** safe-first window and vetoed while export or other guarded activity is active.

## 0.9.0-alpha9.167 — completed Happy Hour receipt durability

- Fix the observed 1 November 2026 regression where **two confirmed Weekend Happy Hours (7.294 + 3.655 kWh)** were initially worth approximately **£3.93** but fell to **£1.31** when the 12:00 booking aged out of Octopus's live joined-event feed.
- Financial reporting can now use independently confirmed **one-hour** reward windows already persisted by the physical grid-import recorder. These windows are strictly financial evidence for **completed** hours; they cannot authorise future Octopus booking, live charging, control commands, or any inverter write.
- Persist per-hour verified import, indicative rate and estimated credit in the lifetime store; retain completed receipts through disappearance of the live booking/plan and Home Assistant restart. Keep a same-day high-water safeguard on previously verified cumulative credit and energy. Never rewrite gross smart-meter import or claim supplier settlement.
- Test the 1 November two-hour regression, joined-feed expiry, restart/rate-change receipt restoration, and rejection of unconfirmed, future or incomplete reward windows.
- **No physical export/control policy changes.** A separate 17:27 observation (2.015 kW metered grid export with zero planned deliberate export while FoxESS reports Self Use and a retained 7 kW Force Discharge setpoint) needs time-aligned physical verification before changing command semantics. DNO export ceiling, 15% paid export cutoff, 10% house floor, EV hold, Power Down and maintenance safety remain unchanged.
- Release/install only after CI validation, and defer the actual Home Assistant restart to the configured **06:00–06:30 safe window** with no active export.

## 0.9.0-alpha9.117 — safer unplugged Ohme continuity and commissioning diagnostics

- Stop unnecessary paid-Agile pauses while Ohme **freshly confirms unplugged** but its zero-power field is missing or old and FoxESS grid-import reads remain unchanged. A non-stale grid-import value may be up to 180 seconds old for this explicit-unplugged proof only, matching the existing control data freshness contract; household load still needs a recent reading, grid import must remain low, and the final export guard independently rechecks the session-only physical proof.
- Connected or uncertain EVs retain the stricter 35-second site corroboration and connected-idle source checks. Positive charging power, connected/charging status, missing physical measurements and genuinely stale evidence still veto export. This does not electrically isolate a shared bus and cannot guarantee instantaneous detection of a newly started charge.
- Add a bounded, non-persistent list of the latest eight **failed** FoxESS whole-site power-balance samples to the commissioning diagnostic, with timestamps, five physical power values, per-source ages, residual and tolerance. The original 90% / last-60 commissioning requirement, physical reserve, DNO export ceiling, Force Discharge proof, safety releases, and overnight Force Charge conditions are **not changed**.
- No changes to scheduling, simulation, ROI, No KEMS baseline, dashboard or the automatic maintenance-window guard. Intended for deployment only through the existing 06:00–06:30 safe automatic maintenance window, and only once CI passes; unattended installation/restart should defer if physical energy activity blocks it.
- Regression tests cover unplugged proof, connected/uncertain and charging vetoes, out-of-date meters, spoofed evidence, bounded failed-sample reporting, and unchanged commissioning threshold. Inspect the following day's physical logs before declaring live proven.

## 0.9.0-alpha9.107 — solar-aware FoxESS AC output and physical export proof

- Correct live paid-Agile FoxESS Force Discharge Power translation: the Modbus parameter caps AC-interface output (including PV), not battery-only output. Alpha9.106's 1.0 kW command during ~3.3 kW PV resulted in ~2.3 kW battery charging and zero export; it could not establish the required discharge-direction proof.
- Set AC output from fresh physical solar plus the independently bounded battery contribution. For unproven control, stage at up to 1 kW *incremental battery export* after the home's unmet solar demand. Physical solar export can add to metered net export, bounded by the independent 7 kW DNO/hardware ceiling.
- Continue to cap every output by the physical battery-discharge plan, battery and inverter ratings, live house/PV evidence and the site grid-export ceiling; fail closed on invalid or insufficient physical headroom.
- Permit the original two physical battery-discharge **and** grid-export direction samples during sunshine. PV-only export does not satisfy battery proof or spuriously trigger a permanent failure lockout. Genuine low-solar direction failures retain their three-sample latch.
- Upgrade the proof protocol from 2 to 3, requalifying any obsolete persisted proof lockout exactly once without discarding the pre-KEMS rollback baseline. Restart still requires new physical proof; this release is **not** asserted live-proven until Home Assistant diagnostics confirm battery power >0 and grid export >0.
- No changes to EV charging/MinSOC hold, cheap Intelligent charging, physical reserve budget, forecast plan, Power Down precedence, Happy Hour, export limit settings or upstream tariff economics. Never treat unknown Ohme as unplugged.

## 0.9.0-alpha9.101 — Recorder-safe KEMS maintenance status

- Fix the Home Assistant Recorder warning that `sensor.kems_maintenance_status` contains more than 16 KiB of state attributes. The maintenance notice is sometimes an intentionally large update payload; it must remain fully readable **live**, but Recorder should store only its compact state and standard metadata.
- Reuse the established Alpha9.17 `MATCH_ALL` Recorder-safe entity wrapper for the previously omitted `KEMSMaintenanceStatusSensor`. Preserve the same entity ID, value, coordinator/orchestrator, live maintenance attributes, update verification, dashboard and restart behaviour.
- Add regression tests to ensure the maintenance wrapper is installed at setup, only the Recorder attribute boundary changes, large live payloads remain available and no optimisation/forecasting/EV/FoxESS/update-installing code is modified.
- Extend the **manually activated export commissioning switch** to permit the existing **Agile Outgoing** tariff as well as **No paid export**, without changing the selected tariff or the normal Agile export optimiser. Other tariffs remain ineligible.
- Preserve the existing 1.0 kW net-export proof, **solar at or below 0.01 kW**, 20% minimum start SOC, fresh EV-unplugged evidence, 15% export reserve, 7 kW configured grid export ceiling, two physical proof readings, 60-second maximum stress phase and verified FoxESS restoration. A change of selected tariff during the test immediately requests restoration; an interrupted test never resumes Force Discharge on restart.
- **Financial split:** the No paid export commissioning path remains ROI-neutral. With Agile selected, real metered export income and subsequent charging costs stay in normal actual ROI; no artificial zero-income entry, doubled income, or invented test revenue is booked.
- No changes to normal live Agile strategy, solar forecasts, grid-only No KEMS baseline/ROI, comparison-switch setting, 25-second FoxESS Modbus polling, or 100%-when-feasible charging goal.
- Release does **not** claim Home Assistant watchdog, go2rtc, Zigbee or cloud timeouts are fixed. After installing, check for *new* Recorder oversize warnings; historic log entries remain in old files.

## 0.9.0-alpha9.100 — optional what-if replay and compact diagnostics

- **No change to live FoxESS or Ohme control, scheduling, forecasting, battery reserve, tariff handling or overnight charging target.** Full KEMS Live and the original no-solar/no-battery grid-only No KEMS ROI baseline are retained.
- Add a **Detailed what-if comparisons** switch under Monitoring and history. Default **On** for existing and new installations, so installing this release alone cannot remove existing comparison data. Explicitly switching **Off** stops the seven-scenario replay and island/timeline reconstruction each scan while preserving lightweight, mathematically equivalent No KEMS comparisons for Today, Yesterday, 7 and 30 days. Other hypothetical comparison sensors remain installed but report unavailable while Off; On restores them without rewriting history.
- Keep the separately calculated grid-only cost basis, actual measured import/export, live Control, payment and ROI ledgers, learning history, forecast and Agile optimiser untouched. Never modify historical records or the user's 100%-when-feasible overnight charge target.
- Limit KEMS diagnostics to the latest 64 EV trace samples with inclusion/omission counts. The original recorder retains all 960 bounded samples for physical EV/charging investigations.
- Add parity regressions for all four No KEMS comparison periods, data-gap semantics, legacy defaults and live-control isolation. This is a performance-oriented switch, not a claim that Home Assistant watchdog restarts are solved.
- **Rollout:** install while the inverter is in a stable mode, verify unchanged KEMS/FoxESS/EV operation and ROI, then turn Detailed what-if comparisons Off; measure the coordinator's update latency and CPU before/after. Flip back On if an engineering comparison is needed. Physical export validation for Alpha9.99 remains independent.

## 0.9.0-alpha9.99 — house-aware physical net-export proof

- Correct FoxESS Force Discharge interpretation: the inverter needs to cover measured non-solar household load **plus** the planned grid export; the previous 1.0 kW *total discharge* stage could produce no measured export when the home consumed more than 1 kW.
- The initial proof now caps the **net export target** to 1.0 kW and bounds total inverter discharge by the independent KEMS total-discharge plan, verified FoxESS export ceiling, battery discharge limit and inverter/solar headroom. Unavailable, invalid or insufficient house/solar telemetry fails closed before any paid-export write.
- Keep the existing two fresh physical battery/grid direction samples, 3-failure lockout, reviewed readbacks, 7 kW DNO export ceiling, EV safety, battery SOC reserve, cheap-period restrictions and restoration safeguards.
- When a 1 kW stage's battery output is insufficient to cover measured home demand, treat absent grid export as inconclusive instead of permanently counting it as an inverter proof failure.
- Migrate the obsolete persisted pre-Alpha9.99 stage lockout only once, after reloading the entire original FoxESS rollback baseline. Fresh physical proof remains mandatory before full Agile output; subsequent genuine failures still persist.
- Add isolated production-function regression tests for home load, solar, ceiling/headroom, invalid telemetry, persisted rollback state and decisive/inconclusive direction evidence.
- This release does not fix the separate Home Assistant watchdog, Modbus polling or cloud Ohme outages. Do not attempt supervised physical export testing until their readiness gates are healthy.

## 0.9.0-alpha9.98 — bounded plugged-in Ohme outage export continuity

- Paid Agile Control only: after a freshly confirmed connected-but-idle Ohme reading, allow a single, non-renewable 60-second outage window instead of immediately cancelling deliberate grid export on cloud API `unavailable`.
- Require recent verified zero EV power and fresh FoxESS whole-site load baseline before entry. The final hardware export guard rechecks the same in-memory continuity evidence; an evidence string or stale flag cannot bypass it.
- Immediately veto continuity on Ohme charging/positive EV power, a house-load rise above the last confirmed idle sample by more than 1.0 kW, newly observed grid import above 0.3 kW, missing/stale FoxESS load data, or elapsed 60 seconds.
- Re-arm only after Ohme explicitly reports connected, not charging, and fresh zero EV power. The window is never persisted across KEMS/Home Assistant restart.
- No change to EV MinSOC hold, no-paid-export control, cheap-slot authorisation, export limits, house-energy reserve, Agile forecasts or financial calculations.
- This software safeguard does not physically isolate the EV from the shared bus. Independent EV-circuit metering is still recommended for hard battery-to-EV protection.

## 0.9.0-alpha9.68 — scheduled tariff renewal

- Added two effective-dated electricity tariff fallback changes while keeping live Octopus/Home Assistant values authoritative in Automatic mode.
- Kept the current fallback unchanged through 30 September 2026.
- From 1 October 2026, removes the former 5% VAT from the existing tariff fallback: 26.9558095238p day, 3.326952381p off-peak and 51.147p/day standing charge.
- From 4 October 2026, switches the fallback to the renewed tariff: 37.17p day, 8.00p off-peak and 55.52p/day standing charge.
- Intelligent extra-slot price corroboration now uses the effective cheap rate for the current date, so the 4 October renewal cannot be rejected for still expecting the old 3.4933p rate.
- Added editable dates/rates on the Tariff and prices options page. Clearing an effective date disables that scheduled change.
- Scheduled values do not override available live Octopus rates.

## 0.9.0-alpha9.67 — physical cheap-charge authority

- Made fresh physical battery SOC authoritative for no-paid-export cheap-period charging.
- Kept the solar-aware no-export target forecast-derived, but removed simulated SOC / simulated charge power from the real charge/no-charge decision.
- When physical SOC is below target, KEMS requests Force Charge up to the configured maximum while respecting available site-import headroom.
- When physical SOC reaches the target, KEMS returns to Self Use and holds with Min SoC-on-grid.
- If physical SOC or the no-export target is unavailable, KEMS does not authorise battery charging.
- Kept Intelligent-slot confirmation, commissioning, ownership/restoration, stale-data, island/EPS and emergency-stop gates unchanged.
- Deliberate/economic Force Discharge, Agile/paid-export control, Import Power Limit writes and Export Power Limit writes remain blocked.

## 0.9.0-alpha9.66 — remove daytime anti-import Force Discharge

- Removed the fixed 50 W daytime anti-import bias and all earlier grid-trim/feedback variants from the current control architecture.
- Removed the anti-import configuration/model state, diagnostics and live Force Discharge exception.
- Restored normal non-cheap live operation to plain FoxESS Self Use; small natural inverter grid import is accepted rather than actively trimmed.
- Kept confirmed-cheap Force Charge and Min SoC-on-grid control unchanged for independent cheap-slot testing.
- Deliberate/economic Force Discharge, Agile/paid-export control, Import Power Limit writes and Export Power Limit writes remain blocked.
- Retained existing commissioning, fail-safe ownership/restoration, stale-data, island/EPS and emergency-stop gates.

## 0.7.0-alpha7 - cross-midnight SOC continuity

- Fixed live simulation day-start SOC so the previous day’s full simulated battery state is carried across midnight instead of resetting to the configured initial SOC before replaying only the cheap-period tail.
- Replays retained previous-day battery behaviour recursively across available history, while still allowing a real observed battery SOC to anchor the simulation when one exists.
- Closes the final pre-midnight interval when the next-day boundary sample is within the normal 30-minute integration cap; larger data gaps carry the last simulated state without inventing extra charge or discharge.
- Preserves carried SOC immediately after midnight even when only one new-day history sample exists.
- Caches completed day-start replays by configuration/history boundary so normal coordinator updates do not reprocess the full retained history every minute.
- Added regression coverage for the former 57.9% overstatement case and the first-sample-after-midnight reset.
- Real FoxESS writes remain hard-blocked.
- Added **Full KEMS Forecast** as a seventh parallel profile and sixth financial scenario while leaving Full KEMS unchanged as the profit-first benchmark.
- Added Forecast.Solar auto-discovery plus a direct, cached Open-Meteo UKMO multi-array tilted-irradiance provider for the proposed East/West/South PV geometry.
- Added conservative forecast fusion, provider agreement/confidence reporting, and hourly solar-shape scaling to the fused production total.
- Added learned remaining-today, tomorrow-total and 24-hour house-demand forecasts.
- Added physical recharge feasibility: overnight charge capacity, maximum achievable morning SOC, full-charge feasibility, additional cheap time to full, forecast-required morning SOC, recharge shortfall and minimum pre-cheap SOC.
- Added hourly forward energy simulation so late-arriving winter solar cannot hide a morning battery shortfall behind a reassuring daily total.
- Added Normal, Watch, Protect and Recovery forecast states. Protect retains only the calculated battery energy needed to avoid predicted day-rate import; Recovery uses solar for home/battery only until the reserve target is restored, then resumes Full KEMS export behaviour.
- Forecast decisions are stamped onto retained snapshots so historical Full KEMS Forecast replay uses the decision actually known at the time rather than applying today's forecast retrospectively.
- Added forecast settings, diagnostics, scenario cost/flow carriers and explainable Home Assistant sensors. Open-Meteo failures use cached data and never disable normal KEMS analysis.

## 0.7.0-alpha6 — parallel scenario comparison

- Added source-specific tariff freshness gating so stale Intelligent-slot signals cannot authorise cheap charging; tariff inputs now fail back independently without making fresh power telemetry stale.
- Tuned the slower Octopus Intelligent slot/schedule sources to a 360-second freshness window while retaining the normal 180-second timeout for live power and fast tariff inputs.

- Added a dedicated what-if replay engine that evaluates six independent system designs from the same retained observations: No system, Solar only, Solar + battery, KEMS no-export, Full KEMS smart control, and Full island mode — grid down.
- Comparison replay is independent of the currently selected export-tariff/live-readiness mode, so no-export can remain active while paid-export Full KEMS is still modelled in parallel.
- Added exact today cost, import/export, solar routing, battery routing, end-SOC, standing-charge and saving-vs-baseline summaries for every scenario.
- Added an explainable saving decomposition: reduced day-rate import, change in cheap-rate import, export income, and Power Down income.
- Added a resilience-only full-island replay with grid import/export forced to zero, EPS output limits, emergency-floor protection, outage survival, unserved energy and first-shortfall reporting; it is excluded from cheapest-scenario financial ranking.
- Full Island Mode now deliberately blocks EV charging before EPS replay, reports that EV energy as intentionally shed rather than unserved house load, and measures resilience against the remaining island/EPS demand.
- Added prepared-outage resilience on top of Full Island Mode: KEMS now finds the minimum starting SOC needed to eliminate energy-limited shortfall, adds a 5% preparation margin, and replays the outage from that prepared target without pretending a larger EPS or any non-EV load-shedding capability exists.
- Prepared resilience explicitly distinguishes an unavoidable EPS-limit shortfall from an energy-capacity shortfall, and reports when even 100% SOC cannot cover the requested outage period.
- Fixed Power Down completion auditing so joined/pre-session samples no longer permanently fail the EV-block check; safety evidence is now accumulated only while the session is actually active, with explicit plan, EV, island-override, and no-active-sample completion reasons.
- Added cumulative midnight-to-now cost timeline data for the five financial scenarios, plus island SOC/load-served/unserved-energy/status timeline data.
- Added Yesterday, 7-day and 30-day retained-history scenario rollups.
- Added smart-simulation cheap/day import-cost splits and solar/grid-to-battery flow accounting used by the comparison engine and diagnostics.
- Added built-in and ApexCharts/Mushroom Compare dashboards.
- Full KEMS and no-export comparison batteries are carried independently across retained days, keeping scenario histories isolated from one another.
- Real FoxESS writes remain hard-blocked.

## 0.7.0-alpha5 — awaiting export tariff / no-export live readiness

- Added an explicit Export tariff status: Active or Not active / awaiting export tariff.
- Awaiting mode values export at 0p/kWh and overrides normal export settings without deleting the configured future export rate.
- Forces self-consumption-first simulation: solar → home → battery, then battery → home, with deliberate grid export disabled.
- Adds solar-aware cheap-period charging targets so the battery retains forecast home cover while leaving conservative PV headroom.
- Power Down remains visible but no battery/export reserve is created while paid export is unavailable; reduction can still come from avoiding import.
- Added export-tariff/no-export status, solar-to-battery flow and overnight charge-target diagnostics.
- Control Lab mirrors the policy in shadow planning but real hardware writes remain hard-blocked.
- Existing alpha4 users migrate with Export tariff status = Active so behaviour does not silently change.

## 0.7.0-alpha4 hotfix — actual lifetime reconciliation

- Makes the persisted daily ledger authoritative for observed/pre-install lifetime energy and billing totals, matching the simulated-ledger approach.
- Corrects stale-source high-water contamination such as frozen live-demand intervals that were later excluded from a day.
- Reconciles house consumption, grid import/export, solar/battery energy, gas, import/export cost and simulated totals on load and every update.
- Deliberately leaves commissioned-only actual system-value counters on their existing commissioning-gated accumulation path.
- Keeps incomplete-day flags intact rather than silently treating repaired history as complete.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4 hotfix — stale live-source protection

- Detects stale live power/SOC sources using Home Assistant `State.last_reported`.
- Uses the existing configurable stale-data timeout (default 180 seconds).
- Stops integrating frozen power values into consumption, cost, learning and simulation totals.
- Marks reporting periods incomplete when stale/missing intervals reduce day coverage.
- Lowers Data Quality and exposes the exact stale logical fields and source ages.
- Makes Control Data Fresh fail safe from underlying source age, not merely the new KEMS snapshot timestamp.
- Adds source report timestamps/ages to diagnostics for troubleshooting connectivity outages.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4

- Fixed blank settings-menu labels when Home Assistant or the browser retained an older custom-integration translation bundle.

# Changelog

## 0.7.0-alpha4 — guided setup and editable tariff UI

- Replaced the single oversized options form with a six-page Home Assistant Configure menu.
- Added automatic tariff mode with user-editable day-rate, off-peak-rate, standing-charge, export-rate, and cheap-period fallback values.
- Added manual tariff mode for users without a supported live tariff integration.
- Added local-time cheap-period start/end controls with correct overnight handling across midnight.
- Preserved confirmed Intelligent extra-slot safety: the cheap rate is used only when the Intelligent slot and active EV charging agree.
- Added guided first-time setup for automatic versus manual tariff selection.
- Allowed manual-tariff installations to run without a current-import-rate entity.
- Split battery, solar/export, financial, monitoring, and Control Lab settings into focused pages with descriptive selectors and units.
- Added alpha3-to-alpha4 migration defaults without changing existing automatic Octopus behaviour.
- Fixed Home Assistant 2026.8 config-flow import failure by using supported high-precision number-selector steps.
- Added tariff-resolution and UI-schema regression coverage; 107 tests pass.
- Real FoxESS and charger writes remain disabled.

## 0.7.0-alpha3 hotfix — simulated period reconciliation

- Made the persisted daily ledger authoritative for all simulated lifetime totals.
- Corrected Month, Year, and All-time export, battery-export, and export-income differences caused when intraday simulation forecasts revised downward.
- Reconciles stored alpha3 totals immediately on load and after every accumulation update without changing actual observed totals.
- Added regression coverage for daily-ledger summation and downward simulated-export revisions.
- Real FoxESS writes remain disabled.

## 0.7.0-alpha3 — KH7 topology, retained Power Down results, and accumulator repair

- Separated the 7kW battery charge/discharge limits, 7kW combined KH7 AC output limit, 7kW island/EPS limit, and an independently configurable whole-site import limit.
- Modelled grid bypass correctly so a 2kW home plus 7kW battery charge is a valid 9kW site import when the installer-confirmed site limit permits it.
- Enforced `solar AC + battery AC <= 7kW` during paced export, Power Down, high-solar operation, island operation, and restoration planning.
- Restricted EPS utilisation and warning thresholds to islanded operation; grid-connected demand now uses bypass/site-import diagnostics instead.
- Added battery-charge, total KH7 output, grid-bypass, total-site-import, limit, and headroom entities for clearer dashboards.
- Persisted a separate last-completed Power Down result after Octopus removes the live event, including SOC, planned energy, maximum output, reward estimates, EV blocking, and completion status.
- Repaired the lifetime accumulator so observed electricity, gas, import/export, and bill evidence accumulate before commissioning while actual system-created value remains commissioning-gated.
- Added native Today, Week, Month, Year, and All-time summaries with separate actual/simulated totals and explicit incomplete-day reporting.
- Prevented a mid-day commissioning change from claiming modelled value created before the physical system was commissioned.
- Added an alpha2 ledger migration that rebuilds recoverable observed totals from retained history without double-counting the temporary single-import-source mapping.
- Added accumulator health, rollover, historical-repair, site-limit, KH7-headroom, EPS-status, and retained Power Down diagnostics.
- Expanded the deterministic safety suite from 12 to 15 checks and added topology, site-import, high-solar, and island-cap regression tests.
- Real FoxESS writes remain hard-blocked: backend available, commands permitted, system commissioned, and control enable all remain off by default.

## 0.7.0-alpha2 — validated scenario fixes

- Blocked EV charging during active Power Down sessions so EV demand cannot reduce the rewardable net reduction.
- Split island battery protection into a 20% conservation threshold and a 10% emergency hardware floor.
- Continued whole-house battery support below the conservation threshold while estimating runtime down to the emergency floor.
- Stopped simulated battery discharge once the emergency floor is reached.
- Added explicit virtual-scenario solar and house-load entities so the Control Lab displays injected scenario inputs rather than the normal time-based simulation.
- Added island battery status, conservation-threshold, emergency-floor, and conservation-active diagnostics.
- Removed the aggregate header toggle from the interactive controls card to prevent accidental simultaneous switch changes.
- Added regression coverage for Power Down EV blocking, low-SOC island runtime, emergency-floor protection, and Control Lab entity selection.
- Real FoxESS writes remain hard-blocked; alpha2 is safe to run before hardware installation.

## 0.7.0-alpha1 — pre-installation control lab

- Added hardware-independent Observe, Simulate, Shadow, and Control planning modes.
- Added a virtual KH7 scenario lab for normal operation, high/low solar, high load, active Power Down, daylight/night grid outage, and unstable grid restoration.
- Added whole-house island planning: solar to house first, surplus solar to battery, battery only for the shortfall, no export, and EV charging blocked.
- Added EPS load, headroom, utilisation, warning/critical thresholds, outage-runtime estimate, and five-minute grid-restoration hold planning.
- Added desired work mode, charge, battery-to-home, battery-export, total-discharge, minimum-SOC, operating-reason, blocked-reason, and next-action entities.
- Added stale-data and emergency-stop fail-safe plans plus a 12-check built-in control preflight.
- Added a dedicated Control Lab dashboard and 11 control regression tests.
- Real FoxESS writes remain hard-blocked; alpha1 is safe to run before hardware installation.


## 0.6.0-beta1

- Consolidated all alpha1–alpha5 monitoring and simulation work into the first main-branch beta.
- Included the corrected Power Down dashboard entity IDs and regression tests.
- Retained strict observed-source isolation, KH7 7kW paced export, home-energy reserve protection, fixed 12p/kWh export, Power Down planning, smooth learning confidence, and seven-complete-day ROI gating.
- Removed generated test caches from the release package and aligned manifest, core, and Python package versions.
- Live inverter control remains disabled; this beta is the stable read-only fallback for the separate 0.7 control-development branch.

### Dashboard hotfix

- Corrected Power Down dashboard entity IDs to match the IDs Home Assistant creates from the visible entity names.
- Added duration and baseline net energy to the Actual vs Simulated Power Down card.
- Added regression checks preventing legacy `saving_session` dashboard IDs from returning.


## 0.6.0-alpha5

- Added read-only Octoplus Power Down / Saving Session awareness using BottlecapDave's joined event data.
- Discover both `power_down` and `saving_session` event/baseline entity names for compatibility across BottlecapDave releases.
- Preserve enough battery for forecast home demand and maximum useful KH7 export during a joined session before the next cheap recharge.
- Maximise session output within the 7kW inverter, 7kW battery-discharge, and configurable grid-export limits.
- Convert the joined event reward at **8 Octopoints = 1p** and keep the Power Down bonus separate from normal fixed 12p/kWh export income.
- Use optional import and export baseline sensors to estimate net baseline, rewardable reduction, bonus, and total session income.
- Added Power Down status, reserve, export-target, baseline, reward, and income entities plus dashboard diagnostics.
- KEMS remains read-only: BottlecapDave's automation handles enrolment and KEMS only reacts to events already present in `joined_events`.
- Reset only the simulated financial ledger; all observed history and learning data remain preserved.

## 0.6.0-alpha4

- Prevented paced battery export whenever learned demand forecasts are unavailable and the remaining battery is needed by the home.
- Added recent-load/current-load reserve fallbacks with a 10% safety margin.
- Added reserve-source, projected pre-cheap grid import, and export-paused diagnostics.
- Reset only the simulated financial ledger; observed learning history remains preserved.

## 0.6.0-alpha3

- Updated the proposal profile to the Fox ESS KH7 7kW inverter.
- Added paced battery export that spreads surplus energy until the next cheap period instead of discharging early in the day.
- Added a dynamic reserve for forecast house demand and a projected 10% SOC target at the next cheap-period start.
- Enforced a combined 7kW solar/battery AC output limit and a separate configurable grid-export limit.
- Corrected overnight charging so the KH7 no longer assumes a 56.42kWh battery can rise from 10% to 100% during a standard six-hour 7kW cheap window.
- Locked proposal export income to the configured fixed 12p/kWh tariff; Flux/time-of-use export rates are ignored.
- Added separate live battery-to-home and actual battery-export power entities, plus target export power, exportable energy, home reserve, hours-to-cheap, and projected-SOC entities.
- Updated live simulated flow to use the current snapshot rather than the most recent retained five-minute sample.
- Changed learning confidence to increase smoothly with elapsed observation time and data coverage.
- Withheld annualised ROI and payback until seven complete 24-hour observation periods are available.
- Preserved alpha2 observed history while resetting only the superseded simulated financial ledger.
- Added the full-width `kems_actual_vs_simulated.yaml` dashboard.

## 0.6.0-alpha2

- Prevented every `sensor.kems_*` and `binary_sensor.kems_*` entity from being used as an observed input source.
- Added strict source ownership validation for Octopus Energy, Octopus Intelligent, Ohme, and FoxESS Modbus.
- Removed circular mappings to simulated grid export, simulated battery power, and KEMS battery outputs.
- Rejected unrelated Stellantis EV connected, charging, and service-battery entities.
- Made official Ohme status authoritative for connected/charging state, with charging power as a safety fallback.
- Corrected the lifetime gas meter to use Octopus `current_total_consumption_kwh`.
- Added source-validation diagnostics and a dashboard warning card.
- Added regression tests proving proposal solar export cannot become observed export income.
- Started a fresh `clean_v6_alpha2` history and lifetime namespace.

## 0.6.0-alpha1

- Added clean v6 history and lifetime storage namespaces.
- Added exact automatic matching for BottlecapDave Octopus Energy, MegaKid Octopus Intelligent, and official Ohme entities.
- Added pre-install mapping of Octopus current demand to house load and grid import.
- Added safe grid import/export normalisation and raw grid diagnostics.
- Added one-click reconfiguration with optional manual review.
- Added a complete all-entities diagnostic dashboard and expanded downloadable diagnostics.

## 0.5.0-alpha3

- Fixed the KEMS options/settings flow failing with a 500 error.
- Replaced the non-serializable regular-expression validator with Home Assistant's DateSelector.
- Kept the commissioning date optional before the physical system is installed.
- Added regression tests for the options-flow schema and Hub classification.


## 0.5.0-alpha2 — ROI and lifetime ledger

- Corrected `integration_type` from `helper` to `hub`, returning KEMS to Home Assistant Integrations.
- Added a permanent all-time energy, cost, earnings, and system-value ledger independent of Recorder retention.
- Added pre-install ROI prediction using accumulated proposal-system simulation value.
- Added configurable system cost, extra costs, grants, commissioning date, maintenance, recorded repairs, inflation, degradation, discount rate, and forecast horizon.
- Added live post-install payback tracking and permanent payback-date recording.
- Added automatic **SYSTEM PAID BACK — PROFIT MODE** with net profit after investment and operating costs.
- Added lifetime electricity, gas, solar, grid, EV, battery, import-cost, export-income, and whole-home totals.
- Added baseline-without-system, avoided-import-value, and actual/simulated system-value calculations.
- Added built-in and advanced ROI/lifetime dashboards, including a filling financial battery.
- Added ROI and lifetime diagnostics and regression tests.
- Control remains excluded.

## 0.4.0-alpha1 — Proposal system simulation

- Added the 9.66 kWp, 21-panel proposal solar model with East, West, and South roof groups.
- Added the Fox ESS KH10 / 56.42 kWh battery profile and 10% reserve.
- Added Intelligent Octopus Go import handling and 12 p/kWh fixed export fallback.
- Added live and simulated grid export, export income, battery flow, solar generation, curtailment, and avoided day-rate import entities.
- Added gas discovery, conversion, daily/monthly tracking, and typical-use learning.
- Added whole-home electricity-plus-gas energy and cost comparisons.
- Fixed predicted energy until off-peak so unknown future slots use learned/current load rather than a single interval.
- Added Live-versus-Simulated desktop, built-in, portrait, and analytics dashboards.
- Added KEMS integration branding and a full brand concept asset.
- Control remains excluded.

## 0.3.0-alpha1 — Observe, Learn, Advise, Simulate

- Added automatic source discovery, retained observation history, learning profiles, explainable advice, and read-only battery simulation.
