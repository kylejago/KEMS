# KEMS Alpha8.0 validation report

Build: `0.8.0-alpha8.0`

Coordinated companions:

- KEMS Web / Pi / public: `0.8.0-alpha8-web.0`
- Managed ESPHome panel: `0.8.0-alpha8-panel.0`

## Behavioural baseline

Alpha8.0 is a consolidation and parity release. The accepted behavioural baseline is KEMS `0.7.0-alpha7.52`; the accepted mobile/PWA baseline is KEMS Web `0.7.0-alpha7-web.33`.

The release must not change:

- the established Agile optimiser outcomes covered by the Alpha7.52 regression suite;
- the shared inverter/export/discharge limits;
- the minimum SOC reserve policy;
- the independent 13-point shadow-command safety validator;
- strict candidate-applied replay/tracking;
- conservative handling of genuine rate-retrieval failures;
- Power Down / Happy Hour priority ordering;
- the real-hardware write block before commissioning;
- the read-only property Web and Cloudflare Access security boundary.

## Alpha8.0 consolidation scope

The release must prove:

- Home Assistant publishes `0.8.0-alpha8.0`;
- property Web, Pi agent and public Web all target `0.8.0-alpha8-web.0`;
- the managed panel YAML, panel verifier and release bundle all target `0.8.0-alpha8-panel.0`;
- the Agile runtime enters the frozen Alpha7.52 compatibility stack through one boundary rather than importing every historical patch directly;
- the compatibility registry preserves the proven installer order and every referenced installer remains packaged and parseable;
- Alpha8 does not start a new version-named Agile patch chain;
- the packaged panel is copied unchanged instead of being version-rewritten at runtime;
- existing managed-panel OTA and reconnect verification remain intact;
- the managed ESPHome YAML validates and compiles in CI;
- Web retains the Web.33 authenticated manifest/PWA install contract through Cloudflare Access;
- the service worker continues to avoid caching live API telemetry or Access login redirects as KEMS assets;
- Live Data and the web panel consume one shared physical panel-state model;
- only the shared PWA bootstrap registers the service worker;
- Compare, Agile, Cost & ROI, Settings, public demo, fixture and Pi-deployment contracts remain intact;
- no Home Assistant service/control write path is added to KEMS Web.

## Required automated checks

### Home Assistant / panel

- packaged managed-dashboard current
- Black
- Ruff
- complete Pytest suite
- Python compile
- HACS validation
- hassfest validation
- ESPHome configuration validation
- ESPHome firmware compile

### Web / Pi / PWA

- JavaScript syntax checks
- unconfigured smoke test and runtime manifest check
- Alpha5 fixture regression
- Alpha6 scenario regression
- connected live fixture regression
- Agile read-only/entity/safety contract
- Compare contract
- historical Web capability regressions
- Web.31 mobile/PWA contract
- Web.32 install-state diagnostics contract
- Web.33 Cloudflare-authenticated manifest contract
- Alpha8 consolidation contract
- Pi deployment checks

## Release decision

Alpha8.0 may be merged and published only when the exact final heads of both coordinated pull requests are green. Web should be published first so `0.8.0-alpha8-web.0` exists before the Home Assistant coordinated bundle is released.

Real FoxESS hardware writes remain blocked until commissioning passes. Alpha8.0 does not relax that boundary.
