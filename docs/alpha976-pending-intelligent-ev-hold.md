# Alpha9.76 — pending Intelligent EV hold

## Live defect

The 1 October 2026 Alpha9.75 live extra-slot test proved the established EV hold, physical MinSOC verification, transient freeze and explicit slot-end release all worked correctly. It also exposed one remaining start-of-slot timing gap.

At 20:43:49 Ohme began charging at about 7.34 kW while the battery supplied about 7.58 kW. The raw Octopus Intelligent binary changed to ON at 20:44:29, but the Intelligent start/end timestamp pair did not finish updating until about 20:44:56. Because Alpha9.75 correctly refused full cheap authority without the complete window, the battery continued supporting the EV until the normal confirmed hold was applied and verified at 91%.

The defect is therefore publication ordering, not the Alpha9.75 hold/freeze contract.

## Alpha9.76 contract

### Pending Intelligent hold

Alpha9.76 adds a narrow hold-only state for the exact publication gap.

The pending hold is eligible only when all of the following are true:

- No Paid Export Control is active and the normal plan is safe Self Use.
- The raw, fresh Octopus Intelligent source is ON.
- Ohme positively reports the EV connected and actively charging with fresh non-trivial power.
- The tariff evidence corroborates the configured cheap rate.
- The only failed Intelligent confirmation check is `Intelligent start/end window is unavailable`.
- Fresh physical battery SOC is available.
- If a site-import limit is configured, fresh grid and battery power prove that replacing current battery discharge with grid import remains within that limit.
- No saving-session, emergency-stop, island/grid-loss or higher-priority control path is active.

When eligible, KEMS requests only:

- Self Use
- MinSOC-on-grid = max(existing requested floor, ceil(physical SOC) + 1%)
- Force Charge = not authorised

The pending state does not mark the tariff as cheap and cannot create any additional battery-charge authority.

### Promotion and release

When the full Intelligent start/end window subsequently confirms, the existing Alpha9.75 confirmed-cheap EV hold takes over using the already-latched floor.

If the raw Intelligent signal turns OFF, the window becomes explicitly contradictory, Ohme disconnects/stops satisfying the pending evidence, No Paid Export exits, or another safety gate wins, the pending state is no longer authoritative and the existing release path restores the normal pre-KEMS MinSOC baseline.

### Timestamp event refresh

`next_offpeak_start` and `offpeak_end` are now included in the critical coordinator refresh inputs alongside Ohme status/connection/charging, Intelligent-slot and off-peak state.

This means the coordinator refreshes immediately when the asynchronous Octopus window timestamps finally arrive instead of waiting for the normal 60-second analysis poll.

The existing Alpha9.75 two-second settling refresh remains unchanged.

### Pending freeze proof

A pending hold may be preserved with zero new writes through transient backend readiness loss only if the current live FoxESS MinSOC readback is already at or above the pending floor.

Historical `last_verified_min_soc_on_grid` from an earlier completed EV session cannot prove a new pending hold when the live readback is unavailable.

Once the full Intelligent window is confirmed, the established Alpha9.75 physically verified freeze/grace behaviour remains authoritative.

## Hardware authority

Alpha9.76 adds no new command entity and no new external system authority.

It does not enable Force Charge before full cheap-window confirmation, Force Discharge, direct Ohme commands, import/export power-limit writes, paid/Agile export control, or automatic Master Control enable.

The only new physical action is the bounded temporary MinSOC raise through the already-reviewed Self Use + MinSOC FoxESS surface.
