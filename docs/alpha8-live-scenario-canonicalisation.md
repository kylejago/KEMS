# Alpha8 live-scenario canonicalisation

This slice is an **ownership migration only**. It moves the proven Agile live
scenario reporting/dashboard layer and its immediately-following managed-dashboard
YAML guard behind one non-versioned Alpha8 facade without changing runtime
behaviour.

## Starting point

The slice starts from exact `main`:

- commit `75a37e21d71b8539570a7dfe03d6339eae2cfc23`
- tree `110ad49bc0bfc3e0a3ea48328fe38676ccf6ca57`

## Proven historical runtime evidence

The existing live-scenario module remains packaged as regression evidence:

- `agile_smart_export_live.py`
- Git blob `38dea9f6d3adb8bbccbbfb935403d514895a052c`

The existing YAML guard also remains packaged as regression evidence:

- `agile_dashboard_yaml_guard.py`
- Git blob `d87dc4c1246a24df22148fd5e4630f8268afd350`

The canonical runtime files use those exact blobs:

- `agile_live_scenario_runtime.py`
- `agile_live_scenario_yaml_guard_runtime.py`

No runtime body is rewritten.

## Why these two seams move together

The historical live dashboard appender ends with `_AGILE_LIVE_VIEW.lstrip()`.
That preserves the original root-level Agile view indentation shape. The next
historical installer, `install_dashboard_yaml_guard()`, repairs that exact output
back under the dashboard's top-level `views` list.

They are therefore behaviour-coupled by installation order even though no frozen
runtime imports either module by historical name. The canonical facade keeps the
same two distinct install positions:

1. install live-scenario reporting/dashboard immediately after rolling planning;
2. install the YAML guard immediately afterwards;
3. only then install settlement dispatch.

No `sys.modules` or package-attribute legacy-name bridge is required. Alpha8
contract tests scan executable imports and fail if either historical module name
becomes an executable dependency.

## Preserved behaviour

The byte-identical live runtime continues to:

- publish `sensor.kems_agile_simulated_battery_soc_now`;
- publish `sensor.kems_agile_live_scenario`;
- keep all live-scenario entities explicitly `simulation_only`;
- distinguish live hardware SOC from simulated Agile SOC;
- prefer a complete current simulated half-hour for routing;
- fall back to the latest completed simulated half-hour without inventing power;
- publish the managed `Agile Smart Export` dashboard view.

The byte-identical YAML guard continues to repair only the historical Agile-view
root indentation marker and leaves other dashboard output untouched.

## Safety boundary

This canonicalisation does not add any Home Assistant hardware service call,
FoxESS provider write path, commissioning bypass, or command-permission path.
`commands_permitted` and `safe_to_write_hardware` cannot become true through this
slice, and real hardware writes remain blocked.

There is no manifest version change, release tag, or coordinated component
version bump.
