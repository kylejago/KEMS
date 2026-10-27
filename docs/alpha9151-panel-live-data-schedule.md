# Alpha9.151 — ESPHome 16×16 panel: live display, two faces, and scheduled LEDs

## Separate display from the controller

**Keep KEMS Product = KEMS and Mode = Control, with Agile Outgoing selected.** The System tab's new **ESPHome panel — display only** card configures the ESPHome device, not the KEMS integration. Changing the overall Product to Live Data intentionally disables energy management and must not be used to switch the panel.

The panel's local `Display Mode` select has two choices:

- **Live Data** (default): observed KEMS FoxESS/EV/house/solar/grid power, physical battery SOC and observed cost. Physical solar + house input have been added so the source animations work. Mixed source-colour indications are illustrative/derived from observed powers, *not* meter-grade allocation claims.
- **KEMS**: the prior Full KEMS Agile replay (advisory simulated energy flows and SOC), shown intentionally as a comparison. The display setting does not enable/disable KEMS simulation, commissioning, EV hold or inverter write permissions.

The former Battery & Solar and Full KEMS display modes are retired. After a panel firmware update, older persisted selector values may need **one explicit selection** of Live Data or KEMS.

## Daily panel on/off schedule

ESPHome device entities exposed on the dashboard:

- `select.kems16x16_display_mode`
- `switch.kems16x16_panel_automatic_schedule` (enabled by default)
- `select.kems16x16_panel_on_time` (06:00 default)
- `select.kems16x16_panel_off_time` (22:00 default)
- `light.kems16x16_panel_brightness`

Both times are **Europe/London local time** (BST/GMT) with 30-minute choices, saved across panel reboots. The on time is inclusive, off time exclusive. Overnight wrap is supported; equal start and end means **always on**. The scheduler checks every 10 seconds. During the off period the panel turns off its WS2812 matrix; on re-entry it restores brightness. If HA clock has not synced or a saved time is invalid, it fails open: leave LEDs on, never stop KEMS control. If scheduling is disabled, manual panel brightness and on/off remain available.

This is a device firmware feature: updating KEMS's HA integration/dashboard **does not prove panel.4 is installed**. After the coordinated release, check `sensor.kems_panel_firmware_version` / panel OTA verification and confirm the physical device reports `0.9.0-alpha9-panel.4`. Do not force an OTA or HA restart during Agile/Power Down export.

## Pi / property and public websites

The Alpha9.149–151 changes are in Home Assistant dashboard/reporting and the ESPHome device. The KEMS Pi agent, property website and public website do **not** need forced version bumps or deployment to maintain their existing protocols. The release bundle continues to pin `property_web=0.9.0-alpha9-web.0`, `pi_agent=0.9.0-alpha9-web.0` and `public_web=0.9.0-alpha9-public.0`.

If those separate clients should later **display physical vs simulated SOC, the final guarded export budget or the panel schedule controls**, that is a separately scoped UI/API integration change and warrants its own repository/source review and tests. No Pi/web deployment is implied by this release.

## Safety/non-regression

No changes to FoxESS writer, KEMS Product or Control selectors, 7kW DNO grid limit, 15% soft reserve/10% hard cutoff, EV charging hold, Power Down, Happy Hour, tariff policy or KEMS update window. Panel changes control **LED output only**.
