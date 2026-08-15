# KEMS coordinated updates

KEMS releases can publish a small `kems-bundle.json` asset plus a SHA-256 companion. The bundle is the compatibility contract between Home Assistant, the managed dashboard/panel, property KEMS Pis and the future public website.

## Components

The schema currently reserves these targets:

- `kems_core` — Home Assistant/HACS integration.
- `dashboard` — dashboard packaged inside KEMS and synchronised on KEMS startup.
- `panel` — managed ESPHome panel configuration and firmware version.
- `property_web` — KEMS Web running on a property's Pi.
- `pi_agent` — the root-only KEMS Pi management/update helper.
- `pi_system` — reserved for explicit supported Pi OS/runtime migrations. It is **not** a blanket `apt upgrade` switch.
- `public_web` — reserved now so the future public KEMS website can implement the same exact-version contract without changing the schema.

A component whose target version has not changed is not updated. A component with a `null` target is not targeted by that release.

## Home Assistant update policy

Automatic updates are opt-in. Once enabled, KEMS checks for a verified bundle periodically. A release that requires a Home Assistant restart is scheduled into the configured maintenance window (03:00–04:00 by default). KEMS can create an automatic Home Assistant backup before installation and can restart Home Assistant inside the window when automatic maintenance restarts are enabled. When backup-before-update is enabled, an unavailable or failed backup is a hard safety gate and the software update is not started.

The first release containing the orchestrator is a bootstrap exception: an older installed KEMS cannot automatically install code it does not have yet, so that release still needs one normal/manual KEMS install. Future compatible releases can then install themselves. Automatic updating remains opt-in after that bootstrap install; installing the feature does not silently enable unattended software changes.

If no coordinated bundle asset exists yet, KEMS can fall back to the Home Assistant `update.kems_update` entity for KEMS-only updates. Exact coordinated bundles take precedence when present.

## Maintenance notice

KEMS publishes a persistent Home Assistant notification and a `kems_maintenance_notice` event. The managed dashboard exposes the same durable state. Notices include the bundle, scheduled time, reason, expected downtime, affected components and completion/failure state.

A successful update remains recorded in update history and is verified after restart rather than being inferred from a queued install.

## Release publishing

`release/kems-bundle.template.json` is the component target map. Update component versions there only when that target has changed. The release workflow renders `__RELEASE_VERSION__` from the GitHub tag, validates the bundle, creates `kems-bundle.json.sha256` and attaches both assets to the GitHub release.

The property web and Pi agent currently share one KEMS-Web appliance release, so their target versions must match. The public web target remains `null` until the public website exists.

## Safety

The update orchestrator does not enable the FoxESS command backend, alter commissioning gates or change the KEMS real-hardware write lock. Energy control and software deployment remain independent safety boundaries.
