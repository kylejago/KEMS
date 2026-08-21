# Start here — KEMS Alpha8.0

KEMS is in the **Observe → Learn → Advise → Simulate → Shadow → Control** engineering sequence. Alpha8.0 is the coordinated cleanup baseline: it preserves the proven Alpha7.52 behaviour while consolidating the Home Assistant, Web/Pi/PWA and managed-panel release families.

## Current coordinated versions

- KEMS / Home Assistant integration: `0.8.0-alpha8.0`
- Managed Home Assistant dashboard: `0.8.0-alpha8.0`
- Managed ESPHome panel: `0.8.0-alpha8-panel.0`
- KEMS property Web / Pi agent: `0.8.0-alpha8-web.0`
- Public `kems.uk` source: `0.8.0-alpha8-web.0`

Android is no longer a separate active KEMS UI implementation. The authenticated HTTPS property website is the primary mobile surface and installs as a PWA.

## What Alpha8.0 changes

Alpha8.0 is a **refactor/parity release**, not a new control-policy release.

The Home Assistant Agile runtime no longer imports the long Alpha7 patch chain directly. The exact proven Alpha7.52 installer sequence is frozen behind one `agile_alpha7_compat.py` boundary while the public runtime entry point stays small. New Alpha8 work belongs in canonical modules; regression coverage prohibits a new `agile_alpha8xx.py` patch pile.

The managed panel now has one authoritative version across the packaged ESPHome YAML, Home Assistant panel-health verifier and coordinated release bundle. KEMS no longer rewrites Panel6 to Panel7 at runtime. CI validates the ESPHome configuration and performs a real firmware compile with CI-only placeholder Wi-Fi secrets.

KEMS Web moves the accepted Web.33 mobile/PWA behaviour into the Alpha8 release family. Live Data and the web panel share one physical panel-state derivation, while `pwa-bootstrap.js` remains the single service-worker registration path. Cloudflare Access authenticated manifest loading, safe-area mobile UI, install diagnostics and API/login cache guards remain part of the release contract.

## Four KEMS product levels

Normal users choose one capability level rather than a long list of engineering scenarios:

1. **Live Data** — actual property monitoring only. Simulation and KEMS control are disabled.
2. **Battery & Solar** — live and simulated battery/solar optimisation using the configured import and export tariffs.
3. **Full KEMS** — forecast-aware whole-home optimisation with smart import tariff support, EV awareness and reserve planning.
4. **Full KEMS Agile** — Full KEMS plus dynamic smart-export optimisation such as Octopus Agile Outgoing.

The normal mode selector is **Live / Simulate / Control**. Shadow remains an engineering commissioning stage and is intentionally hidden from the normal user workflow.

## Behavioural baseline

Alpha7.52 is the frozen behaviour baseline for Alpha8.0. The parity release retains, among other established contracts:

- solar-aware shared-inverter headroom;
- latest-safe-start/deadline protection;
- progressive Agile price publication without invented prices;
- no-reserve handling for verified clean Octopus publication gaps, with re-ranking when the price appears;
- conservative fallback on retrieval ambiguity;
- Power Down and Happy Hour priority handling;
- current-routing, dashboard and panel reporting parity;
- maximum-discharge plan reconciliation;
- tomorrow no-reserve reporting and sub-tolerance residual normalisation.

## Panel

The managed 16×16 ESPHome panel exposes the same four product levels as KEMS. Full KEMS Agile consumes the final coherent `current_routing_snapshot`, including grid import/export, solar, battery-to-home, battery export and simulated SOC.

Existing KEMS-managed panels remain eligible for automatic ESPHome compile/OTA/version verification. A first unmanaged adoption still requires one deliberate manual install before KEMS may manage subsequent OTA updates.

## Mobile and remote property access

The authenticated HTTPS property site is the supported installable KEMS mobile app. It remains read-only and does not store a Home Assistant long-lived token.

Remote access keeps the security boundary:

**Cloudflare Access → property tunnel → KEMS Web on localhost:4173 → same-origin read-only KEMS gateway → local Home Assistant/KEMS**

The tunnel does not expose Home Assistant, SSH, Pi management ports or the wider LAN. Local `http://kems-pi.local:4173` remains useful for appliance management but is not the standalone-PWA installation route.

## Safety boundary

Alpha8.0 does **not** enable new real FoxESS writes. The 7 kW shared inverter ceiling, configured grid/export limits, minimum SOC reserve, independent 13-point command validator, strict replay/tracking and commissioning gates remain authoritative.

Physical control remains blocked until commissioned hardware mappings, battery/grid direction, site limits and the vendor backend pass commissioning. The hardware-control contract remains vendor-neutral so future inverter backends can implement the same KEMS policy interface without forking the optimiser.

## Release gate

Before Alpha8.0 is published, the coordinated branches must pass:

- packaged managed-dashboard check;
- Black;
- Ruff;
- complete Pytest regression suite through the Alpha7.52 baseline and Alpha8 consolidation contracts;
- Python compile;
- HACS validation;
- hassfest validation;
- ESPHome configuration validation and firmware compile;
- complete KEMS Web fixture/contract/PWA/Pi deployment suite;
- exact coordinated version/bundle checks.

## Key documentation

- `README.md` — project overview and retained feature documentation
- `VALIDATION_REPORT.md` — current Alpha8.0 release gate
- `docs/agile-smart-export.md` — canonical Agile behaviour
- `docs/hardware-backend-contract.md` — vendor-neutral hardware adapter contract
- `docs/commissioning-checklist.md` — physical-system commissioning gates
- `docs/control-boundary.md` — real-control safety boundary

Historical one-release documents under `docs/` keep their original Alpha7 version references intentionally.
