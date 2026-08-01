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
