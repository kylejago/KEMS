# KEMS 0.6.0-alpha1 clean build

This build keeps KEMS classified as a Home Assistant hub integration and adds:

- a fresh KEMS storage namespace;
- exact matching for the three installed Octopus/Ohme integrations;
- automatic use of Octopus current demand before FoxESS is installed;
- non-negative grid import and export magnitudes;
- signed grid net power with an explicit direction and sign convention;
- raw grid source diagnostics;
- a dynamic dashboard listing every current KEMS entity;
- expanded downloadable diagnostics;
- one-click rescanning with optional manual review.

The manifest must contain:

```json
"integration_type": "hub",
"version": "0.6.0-alpha1"
```
