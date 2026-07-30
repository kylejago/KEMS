# Changelog

## 0.3.0-alpha1

- Added automatic Octopus, current Ohme status/power/battery, and FoxESS Modbus entity discovery.
- Added automatic enrichment when optional providers are installed later.
- Added FoxESS battery-power derivation from Battery Voltage and Battery Current when no direct power entity exists.
- Added persistent rolling observation history.
- Added weekday/weekend quarter-hour learning profiles and confidence.
- Added explainable advice with priorities and confidence.
- Added read-only tariff and battery simulation.
- Added data-quality, learning, advice, and simulation entities.
- Added reconfigure and options flows.
- Kept the complete integration read-only; no device-control services are called.
