# KEMS branding

KEMS has one canonical brand family across Home Assistant, the property Pi, `kems.uk`, GitHub, the companion app, installers and future hardware backends.

## Canonical master

- `docs/assets/kems-logo-master.svg` — source-of-truth full KEMS logo. It combines the home, solar, battery, managed energy-flow and EV-charging concepts with the KEMS wordmark and **Kyle Energy Management System** subtitle.
- `docs/assets/kems_full_brand_concept.png` — presentation/background treatment of the same energy-system concept.

The master lockup is the default visible brand for website headers, public pages, documentation covers, installer/setup surfaces and other locations with enough horizontal space. Do not replace it with an unrelated monogram, lightning-bolt mark or a different KEMS wordmark.

## Product variants

- `custom_components/kems/brand/icon.png` — compact square integration icon for Home Assistant, HACS, favicons and similarly constrained square surfaces.
- `custom_components/kems/brand/logo.png` — compact horizontal wordmark for small Home Assistant surfaces where the full master is not practical.
- The 16×16 panel uses a deliberately simplified pixel treatment rather than attempting to reproduce the full master artwork.

Compact variants are derivatives of the same brand, not alternate logos. They should preserve the blue/cyan/green energy palette, yellow solar cue and the home/energy-system identity wherever the available resolution permits.

## Web and Pi distribution

KEMS Web.16 mirrors the canonical master into both of its presentation roots:

- `KEMS-Web/public/brand-lockup.svg` — local property/Pi dashboard, Remote Access setup and installable web app.
- `KEMS-Web/public-site/brand-lockup.svg` — public `kems.uk`, delayed demo, property-access entry point and privacy pages.

The property and public Web copies must remain visually identical to the canonical master. The compact square Web `logo.svg` remains only for favicons, PWA/loading states and other square icon slots.

The Raspberry Pi first-boot status page also renders the canonical energy-system lockup so the appliance never falls back to a separate temporary brand during setup.

## Home Assistant and hardware

Home Assistant/HACS continues to use the compact canonical `brand/icon.png` and `brand/logo.png` assets because those surfaces impose small/square artwork constraints. No optimizer, tariff, safety or hardware-control behavior depends on branding.

The ESP32 16×16 panel may use a simplified pixel KEMS identity, but it must be treated as a resolution-specific derivative of this master rather than a new brand family.
