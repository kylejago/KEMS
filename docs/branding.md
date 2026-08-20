# KEMS branding

KEMS has one canonical brand family across Home Assistant, the property Pi, `kems.uk`, GitHub, companion applications, installers and future hardware backends.

## Canonical master — exact supplied SVG

`docs/assets/kems-logo-master.svg` is the **single source of truth** for the KEMS visual identity.

The canonical file is the exact SVG supplied and approved for KEMS. It must be copied or mechanically rasterised; it must not be redrawn, reinterpreted or replaced with an older KEMS concept.

- Size: **877 bytes**
- SHA-256: `ef53e22bdff4e4ebd81007c3a6d5f28da0384f547e9036a7be7e3bf2d420b464`

`docs/assets/kems_full_brand_concept.png` is retained only as historical/presentation artwork. It is **not** the canonical logo and must not replace the SVG on user-facing surfaces.

## Product variants

- `custom_components/kems/brand/icon.png` — 256×256 optimised mechanical rasterisation of the canonical SVG for Home Assistant/HACS square artwork.
- `custom_components/kems/brand/logo.png` — 256×256 optimised mechanical rasterisation of the same canonical SVG for Home Assistant raster artwork.
- The 16×16 physical panel may use a resolution-specific pixel treatment because it cannot reproduce the SVG faithfully.

The raster files are derivatives, not alternate logos.

## Web and Pi distribution

From KEMS Web.19 onward, `KEMS-Web/brand/kems-logo.svg` and the user-facing `public` / `public-site` SVG assets are byte-for-byte copies of this canonical master.

The same exact SVG is used on the property dashboard, Remote Access, setup/loading surfaces, `kems.uk`, the delayed demo, property sign-in and Pi first boot. Web.19 also advances the PWA cache so older branding is not pinned after upgrade.

## Public demo and property login

Web.19 adds a deliberately sanitised public demo feed delayed by at least seven days. It exposes aggregate evidence only and does not expose Home Assistant credentials, entity IDs, device identifiers, live control or Pi-management APIs.

Property sign-in is handled by Cloudflare Access/App Launcher rather than a KEMS password database. Property tunnels continue to expose the read-only KEMS Web origin only; local Pi-management and Home Assistant control boundaries remain private.

## Home Assistant and hardware safety

Branding, demo and login changes do not alter KEMS optimisation, tariffs, Panel7 behaviour, safety interlocks or FoxESS control gates. Real FoxESS writes remain governed by the existing commissioning and safety protections.
