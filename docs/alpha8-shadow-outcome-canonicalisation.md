# Alpha8 shadow/outcome canonicalisation

This slice is an **ownership migration only**. It moves the proven Alpha7.23
shadow-command parity and Alpha7.24 routed outcome-parity layers behind one
non-versioned Alpha8 boundary without changing their runtime bodies.

## Exact retained runtimes

- Alpha7.23 shadow runtime Git blob:
  `d943eb70cb1bccc5f4a0a831ca8be65004228b11`
- Alpha7.24 outcome runtime Git blob:
  `c5de2199ad657c80b5c2e2a28fcdfed8327074ed`

`agile_shadow_command_runtime.py` and `agile_outcome_parity_runtime.py` reuse
those exact blobs. No runtime body is rewritten.

## Why the pair moves together

Alpha7.24 imports Alpha7.23 by its historical module name, captures the original
build, evaluate and decision-record functions, then patches that module object in
place. Frozen Alpha7.25 imports both historical names and later Alpha7.28 and
Alpha7.31 patch the same Alpha7.23 object again.

The canonical `agile_shadow_outcome.py` facade therefore binds the historical
Alpha7.23 name to the canonical shadow runtime before importing the unchanged
Alpha7.24 runtime. It then binds the historical Alpha7.24 name to the canonical
outcome runtime. This preserves the proven shared-object patch chain without a
version-named Alpha8 patch module.

## Preserved behaviour

The migration keeps the exact rolling-optimiser shadow target, independent
13-point validation, price-horizon hold visibility, deadline override evidence,
proposal/live solar-aware house headroom, routed inverter AC normalisation,
outcome tracking, and compact decision evidence.

Historical Alpha7.23 and Alpha7.24 files remain packaged as regression evidence.
Historical compatibility-order metadata remains untouched.

## Safety boundary

This remains simulation/shadow only. No Home Assistant hardware service call is
added and no FoxESS provider write path is added. `commands_permitted` remains
false and `safe_to_write_hardware` remains false; real hardware writes remain blocked.
Commissioning is not bypassed.

There is no release, tag or manifest-version change in this cleanup slice.
