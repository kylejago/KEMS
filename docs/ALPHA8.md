# KEMS Alpha8.0 consolidation

Alpha8.0 is the coordinated cleanup baseline for the KEMS platform. It deliberately starts as a **behaviour-preserving refactor release** rather than a new control-feature release.

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

No new `agile_alpha8*.py` version-named runtime patch modules are permitted. Future Alpha8 changes belong in stable, purpose-named modules. The frozen Alpha7 compatibility files remain in the package during the Alpha8.0 parity release so the existing regression suite can prove that consolidation has not silently changed behaviour.

## Panel baseline

The Home Assistant panel manager and the shipped ESPHome YAML use the same `0.8.0-alpha8-panel.0` version. CI validates and compiles the managed ESPHome configuration with placeholder Wi-Fi secrets; real credentials never enter the repository.

## Release gate

Alpha8.0 is not releasable until all of the following are green:

1. Home Assistant Black, Ruff, pytest and compile checks.
2. Existing Alpha7 regressions through Alpha7.52.
3. Alpha8 release-family and compatibility-boundary contracts.
4. HACS and hassfest validation.
5. ESPHome configuration validation and firmware compile.
6. KEMS-Web full contract suite, including Web.33 Cloudflare-authenticated PWA regression.
7. Cross-component bundle versions agree with the coordinated Alpha8.0 family.

Only after this parity gate passes should Alpha8 begin taking behavioural changes or new control capabilities.
