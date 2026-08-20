# KEMS branding

KEMS has one canonical brand family across Home Assistant, the property Pi, `kems.uk`, GitHub, the companion app, installers and future hardware backends.

## Canonical master — approved artwork

`docs/assets/kems_full_brand_concept.png` is the **source of truth** for the KEMS visual identity. It is the exact approved artwork: blue house/roof, yellow sun, blue solar panel, green battery/energy arrow and plug, the blue-to-green **KEMS** wordmark, and the **Kyle Energy Management System** subtitle.

The file is 2,156,120 bytes and its SHA-256 is:

`67ad8c3ee349a35de23f5a9040ce27c18b5cf347454f777cf1f55a6f905eb01f`

`docs/assets/kems-logo-master.svg` is retained only as a historical/redrawn approximation. It is **not** an approved master and must not be used on user-facing surfaces.

Any website/header/icon variant must be a crop, scale, mask or other mechanical derivative of the approved PNG. Do not redraw the house, solar, battery, plug, wordmark or subtitle.

## Product variants

- `custom_components/kems/brand/icon.png` — compact Home Assistant/HACS icon where a square asset is required.
- `custom_components/kems/brand/logo.png` — compact Home Assistant logo where the full approved artwork is not practical.
- The 16×16 panel uses a deliberately simplified pixel treatment because the physical resolution cannot reproduce the approved artwork.

Compact variants are resolution-specific derivatives, not alternate logos.

## Web and Pi distribution

From KEMS Web.18 onward, KEMS Web obtains the approved PNG directly from this repository, verifies the SHA-256 above, and distributes that exact file with both the property appliance and public `kems.uk` build.

The Web `brand-lockup.svg` and `logo.svg` files are crop wrappers only: they display regions of the approved PNG and contain no redrawn KEMS artwork. This keeps the exact approved image authoritative while still supporting wide header and compact icon slots.

The same approved source is used by property headers, loading states, Remote Access setup, `kems.uk`, demo/login/privacy/404 pages and setup/install experiences.

## Home Assistant and hardware

Branding changes do not alter KEMS optimisation, tariffs, safety interlocks, panel control or FoxESS write protection. Real FoxESS writes remain governed by the existing commissioning and safety gates.
