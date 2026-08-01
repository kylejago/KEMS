# Corrected KEMS ROI build

This package is **KEMS 0.5.0-alpha2**.

The Home Assistant manifest is deliberately configured as:

```json
"integration_type": "hub"
```

After copying the package into a new GitHub feature branch, verify:

```text
custom_components/kems/manifest.json
```

contains both:

```json
"integration_type": "hub",
"version": "0.5.0-alpha2"
```

Recommended branch name:

```text
feature/roi-lifetime-ledger-fix
```

## Alpha 3 settings-flow repair

The commissioning date now uses Home Assistant's serializable `DateSelector` instead of `vol.Match`, preventing the settings/options flow from returning HTTP 500 while preserving an optional blank pre-install date.
