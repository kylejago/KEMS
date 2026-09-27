# Alpha9.69 — shadow-only release scope and proof gates

Date: 27 September 2026. PR #296 based on released Alpha9.68 main
`8663995905d8b272d8d10095eceafc7bf3e6a67a`.

## Actual release scope

This is a **simulation, diagnostic and physical-evidence** release, NOT an
activation of the proposed EV-grid/house-battery shared-bus routing. The user's
existing reviewed Alpha9.68 Control-mode cheap-period planner remains the
authoritative physical path. `ControlEngine.plan` invokes the new
`_no_export_cheap_plan` only outside Control mode; coordinator separately
calculates its proposed shadow state while Control mode remains active, and
exposes `alpha969_shadow_plan` in KEMSData, HA diagnostic sensor and
diagnostics. It never forwards that proposal to the Happy Hour, Ohme or FoxESS
physical backends. The sticky `alpha969_routing_shadow_only` gate and
reason-family check reject any accidental new write even if the operating
reason is rewritten by an overlay.

The approved Alpha9.68 physical control contract is unchanged: only bounded
Self Use, confirmed-cheap Force Charge and MinSOC-on-grid with prior-state
ownership/restoration; still no economic Force Discharge, import/export
power-limit writes or paid-export actuation. Normal commissioning, Master
Enable and safety gates still apply to that *existing* authority. No new
KH7 output-control command is enabled.

## Existing measurements and property topology

The owner has confirmed grid and inverter feed EPS/changeover equipment and
Henley blocks downstream feed **both** main and EV consumer units. This is a
shared bus, so KEMS must describe the desired EV-grid/house-battery split as
a **net allocation**, never physical isolation or separate individual AC feeds.

KEMS already measures Ohme status/power, FoxESS Load/PV/battery/grid powers,
SOC, confirmed tariff and source freshness. It records snapshots every five
minutes. The Alpha9.69 read-only `shared_bus_ev_audit` compares the measured
non-EV house/battery allowance and equivalent EV grid import, conservatively
accounting for solar surplus. It preserves the Ohme power report age and
refuses stale/inconsistent/unknown EV scope. The current result is a
diagnostic sensor and export field; `shared_bus_ev_evidence` provides bounded
24-hour status counts and up to 72 retained samples. The **candidate** KH7
site-output ceiling is diagnostic, never a physical setpoint.

Earlier Alpha9.59 evidence recorded a bounded 7 kW Force Charge request,
approximately 6.8 kW actual battery charging, approximately 8.1 kW site
import and pre-KEMS Self Use/MinSOC restoration. This is existing proof for
the reviewed old write scope, not for the proposed new target-limited or
simultaneous shared-bus route.

## Required before merge and tag

1. Verify exact candidate HEAD is based on the reviewed main and all push/PR
   Validate, ESPHome panel, HACS and hassfest jobs are green, including legacy
   Alpha9.60/9.67 physical SOC/target/charge assertions and independent
   shadow-versus-live tests.
2. Manifest version, maintenance bundle reason and release-identity
   assertions must all identify `0.9.0-alpha9.69`.
3. PR title/body and release notes must state **shadow-only observability
   plus unchanged existing live control**, rather than claiming the desired
   new physical EV routing is live.
4. Merge the frozen reviewed candidate, verify its exact main merge SHA,
   release tag target, generated bundle and SHA-256 checksum asset. Do not
   tag the draft branch or bump Pi/Web/panel component versions.

## Separate gate for expanded physical routing

Use the retained evidence in `alpha969-physical-evidence-gates.md` and any
more granular read-only event trace to establish site-balance behaviour at
EV start/steady/stop, tariff transitions and low SOC. Independently confirm
the KH7 exposes a **supported bounded output-control** mechanism and that
measured import/Ohme/battery responses close the loop on the shared bus.
Self Use and MinSOC alone do not enforce that allocation. Repeat supervised
target-limited below-floor charge, headroom and mode/MinSOC restoration;
prove stale-data, grid loss/EPS and Power Down priority paths. If no supported
output-control route exists, retain the EV-active SOC hold fallback. These
conditions require a **new separately reviewed live-authority change**;
merging this shadow-only release never waives them.

Status: shadow-only candidate may proceed after exact-head release proof.
Expanded physical routing is explicitly NOT released.
