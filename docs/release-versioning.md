# KEMS release versioning and canonical source policy

KEMS release numbers identify a tested repository state. They do **not** identify
implementation modules.

## Canonical-source rule

New behaviour must live in files named for the responsibility they own, for
example `agile_forecast_arbitrage.py`, `agile_simulation_presentation.py` or
`commissioning_evidence.py`.

Do not create a new implementation file merely because the release number
changes. In particular, Alpha8 maintenance releases must not create chains such
as `agile_alpha81.py`, `agile_alpha82.py`, `commissioning_alpha81.py` or similar
version-named patch modules.

Historical Alpha7 files remain frozen compatibility/regression evidence. Their
presence does not authorise a new version-named runtime chain.

## Release identity

For a KEMS HA release, the release identity belongs in the release metadata:

- `custom_components/kems/manifest.json`;
- the rendered coordinated `kems-bundle.json`;
- the GitHub release/tag;
- release notes and changelog material where applicable.

The automatic updater compares the installed integration version with the
`kems_core` target in the published release bundle. Therefore a repository state
that must be delivered automatically requires a new release version; moving
`main` alone is not an update signal.

Component versions change only when that component has a new release. A KEMS HA
maintenance release can therefore advance the HA/dashboard component while the
Pi/Web and ESP32 panel remain on their existing coordinated versions.

## Safety

Versioning never changes the commissioning boundary. Real hardware writes remain
blocked until the separate commissioning and operator-enable contracts explicitly
permit them.
