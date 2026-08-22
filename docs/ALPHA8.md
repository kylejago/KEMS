# KEMS Alpha8.0 consolidation

Alpha8.0 is the coordinated cleanup baseline for the KEMS platform. It deliberately starts as a **behaviour-preserving refactor release** rather than a new control-feature release.

## Consolidation status

The Alpha8 ownership and compatibility migration is now **closed**.

PR #132 (`b84ce059020d0145527595c4d4680605eff3c276`) completed the residual historical import-identity audit after the live compatibility registry had already been moved to functional canonical owners. The resulting architecture is documented in `docs/alpha8-architecture.md` and mechanically protected by `tests/test_alpha8_closure_audit.py`.

Closing the migration does not bump the release family and does not itself change behaviour. KEMS remains on the coordinated Alpha8.0 baseline below, with real FoxESS hardware writes still blocked.

## Coordinated release family

- Home Assistant integration: `0.8.0-alpha8.0`
- Property Web / Pi / public site: `0.8.0-alpha8-web.0`
- Managed ESP32 panel: `0.8.0-alpha8-panel.0`
- Legacy Flutter Android app: retired after the authenticated Web.33 PWA passed real-device standalone acceptance

The components retain separate version strings because they have different delivery mechanisms, but they are released and validated as one Alpha8.0 train.

## Behaviour baseline

The Home Assistant behaviour baseline is `0.7.0-alpha7.52`. Alpha8.0 must preserve its Agile decisions, routing, SOC accounting, price-plan selection, deadline protection, maximum-discharge safety, no-reserve publication-gap behaviour, full-battery solar routing, reporting and hardware-write safety.

The Web/mobile baseline is `0.7.0-alpha7-web.33`. Alpha8.0 must preserve the authenticated Cloudflare Access PWA path, credentialed manifest loading, service-worker cache/authentication guards, responsive property UI and read-only property boundary.

## Agile consolidation rule

The historical Alpha7 runtime patch sequence is frozen behind `agile_alpha7_compat.py`. `agile_smart_export_runtime.py` is again a small canonical entry point instead of importing dozens of release-specific patch modules directly.

The live PRE_BASE / POST_BASE registries now use functional canonical owners. Historical Alpha7 files remain packaged where required as frozen regression evidence or deliberate compatibility dependencies, and narrow legacy-name bridges remain where frozen consumers genuinely require canonical module identity.

No new `agile_alpha8*.py` version-named runtime patch modules are permitted. Future behavioural changes belong in stable, purpose-named modules. Do not resume cosmetic canonicalisation or remove a historical compatibility bridge merely for naming consistency; the architecture and removal criteria are defined in `docs/alpha8-architecture.md`.

## Panel baseline

The Home Assistant panel manager and the shipped ESPHome YAML use the same `0.8.0-alpha8-panel.0` version. CI validates and compiles the managed ESPHome configuration with placeholder Wi-Fi secrets; real credentials never enter the repository.

## Parity gate result

The Alpha8 ownership/compatibility parity gate has passed through PR #132. The exact-head closure candidate passed the required Home Assistant validation, existing Alpha7 regressions, Alpha8 contracts, HACS, hassfest, ESPHome validation and real managed-panel firmware compile before merge.

The closure contract remains active after that merge. Future changes must continue to keep the relevant gates green on one exact candidate head; CI evidence from an earlier candidate must not be reused after the head changes.

Cross-component behavioural or release work must also preserve the coordinated family contracts with KEMS-Web and the managed panel.

## Development after closure

Behavioural development may now proceed only from the closed canonical architecture. It must use purpose-named modules, preserve the existing Alpha7.52 behaviour baseline unless a change is explicitly intentional and tested, and keep commissioning independent from software architecture cleanup.

Commissioning-readiness work may prepare read-only FoxESS discovery, backend interface verification, command-envelope validation, dry-run/shadow comparison and explicit operator enable gates. It must not enable real hardware writes until actual commissioning requirements are satisfied.

The permanent architecture boundary and archival criteria are in `docs/alpha8-architecture.md`.
