# Alpha8 settlement-dispatch canonicalisation

This change is an **ownership migration only** for the proven Alpha7.17 Agile
settlement-slot dispatch and dashboard presentation.

## Canonical ownership

- `agile_settlement_dispatch.py` owns installation and compatibility routing.
- `agile_settlement_dispatch_runtime.py` is byte-identical to historical
  `agile_alpha717_dispatch.py` at blob
  `7417342ecd5a8ba090a78b56283c8e5607e4a924`.
- `agile_settlement_dispatch_dashboard_runtime.py` is byte-identical to
  historical `agile_alpha717_dashboard.py` at blob
  `984164ced70196357acf6b85a63e63b07af23c60`.

The historical source files remain packaged regression evidence and the
historical Alpha7 compatibility-order metadata remains unchanged.

## Module identity

Frozen downstream runtimes still import `agile_alpha717_dispatch` and call its
helpers. The canonical facade therefore binds that historical import name to the
canonical byte-identical dispatch runtime object before Alpha7.17 dispatch is
installed. The dashboard has no corresponding module-identity dependency, so it
is loaded lazily only at its historical install position and its historical name
is not aliased.

## Preserved behaviour

The migration preserves the Alpha7.17 deadline-pressure modes, maximum-discharge
fallback when the 10% target is physically unreachable, deadline-following and
price-optimised current-slot targets, house-first discharge/export headroom,
elapsed-slot routing evidence, rolling current-slot target publication, and the
existing dispatch dashboard presentation.

There is no tariff, SOC, export-limit, inverter-limit, discharge-limit,
commissioning, or control-policy change in this slice.

## Safety

KEMS remains simulation/shadow only. No Home Assistant hardware service call or
FoxESS provider write path is added, `commands_permitted` and
`safe_to_write_hardware` remain false, and **real hardware writes remain blocked**.

There is no release, tag, or version bump; the integration remains
`0.8.0-alpha8.0`.
