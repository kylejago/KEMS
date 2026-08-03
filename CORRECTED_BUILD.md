# KEMS 0.6.0-alpha3 KH7 paced-export correction

This build retains the alpha2 source-isolation protections and changes only the
proposal simulation and presentation layers.

Key changes:

- Fox ESS KH7 7kW inverter profile;
- 7kW charge and discharge limits;
- combined solar plus battery AC output capped at 7kW;
- fixed 12p/kWh simulated export tariff;
- paced battery export toward the next cheap period;
- forecast house-energy reserve before battery export;
- projected SOC target close to 10% at the next cheap-period start;
- preserved observed learning history;
- one-time reset of superseded simulated financial value;
- smoother learning confidence and seven-complete-day ROI gate.

The manifest contains:

```json
"integration_type": "hub",
"version": "0.6.0-alpha3"
```
