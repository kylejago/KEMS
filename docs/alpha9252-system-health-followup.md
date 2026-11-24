# Alpha9.252 system health follow-up

Scope: KEMS and its dependencies, not unrelated HA integrations. Reviewed the
24 November 2026 21:16 diagnostic, System Monitor and Core/Supervisor/host logs.

## Implemented

- Use one commissioning evidence snapshot and one Agile state reference per
  diagnostic. Present the same operator readiness as the HA sensor while retaining
  original evidence state and booleans for troubleshooting; no gate changes.
- Explicit current routing provenance: advisory pre-guard model, guard cap,
  final desired and authorised target, measured grid CT, model/physical SOC,
  same-scan verified lower bound and conditional/theoretical arrival. Preserve
  the historical route schema and the independent digital twin. No measurement,
  dispatch or reward is inferred from a single CT sample.
- Reuse the cache's existing private serialized result for isolated JSON
  checkpoint copies, avoiding repeated recursive copies where supported. Full
  SHA-256 input checks, cache version, SOC carry, future/current-day exclusion,
  fallback and numerical outputs remain unchanged. Await cache restoration in a
  HA executor when available, rather than blocking the event loop during startup.
- Retain the complete Python 3.14 unit suite and add a separate exact-version
  Home Assistant Core 2026.11.3 import smoke test using real HA APIs.
  This checks import compatibility, not setup against a live installation,
  real FoxESS/Ohme devices, or external custom integration compatibility.

## Evidence and remaining limits

The latest host snapshot showed CPU 1.6%, RAM 27%, disk 23.2%, CPU 31 C.
The latest KEMS scan was about 3 s; the history worker spent about 0.96 s on
fingerprints. Do not weaken exact historical input invalidation, skip changed
same-scan sensor publication, or bypass the physical guard to reduce timing.
No measured improvement is claimed until post-install diagnostics. Further
hot-path fingerprint optimisation and publication attribution remain #405.

The latest diagnostic had requested battery export 0.899 kW, physical guard
0.469 kW, final desired total discharge 1.323 kW and separate measured CT
export 0.656 kW. Physical SOC 20%, verified conservative lower bound 19.362%,
independent twin 22.03%; these different authorities must not be forced equal.
Completed historical continuity remains separate. The 15% export floor and
10% household floor remain independent.

Retain frozen compatibility wrappers and existing entity contracts until their
dependency/byte-identity regression tests permit removal. Alpha9.250 already
labels the live dashboard proposal, permitted target and CT measurement;
avoid another dashboard patch solely to rename the same fields. The new
diagnostic projection labels the existing legacy route schema explicitly.
No external integrations are removed or updated by this bundle.

FoxESS Modbus and legacy Octopus Intelligent deprecation warnings are upstream
compatibility issues; do not change their packages or install an unverified
version. Ohme plan observation is read-only, and supplier confirmation of
extra-slot tariff eligibility remains outstanding. No historic gap filling,
late Power Down baseline recovery or live solar-only inverter-mode pilot.
