# Alpha9.80 — runtime dashboard YAML hotfix

## Incident

Alpha9.79 correctly reconciled the managed dashboard entity IDs, but one edit in
the Alpha9.37 runtime dashboard compatibility layer removed an inline Jinja
assignment without also removing that line's leading indentation.

That left two Live Data markdown blocks shaped like:

```yaml
content: |
                    | Energy | Live Data |
          |---|---:|
```

The first table row was over-indented while the following Markdown separator
returned to the normal indentation. Home Assistant therefore interpreted the
separator as YAML syntax and failed to load `/config/kems_master_dashboard.yaml`.

The live HA log reported:

- `while scanning a block scalar`
- line 141
- `expected chomping or indentation indicators, but found '-'`

## Fix

Alpha9.80 restores the correct indentation in both affected runtime Live Data
markdown blocks:

```yaml
content: |
          | Energy | Live Data |
          |---|---:|
```

## Regression protection

A new test applies `repair_dashboard_contract()` to the managed Master dashboard
and then parses the resulting bytes with `yaml.safe_load`.

This protects the generated runtime payload rather than only checking that the
repository and packaged dashboard files match byte-for-byte.

## Safety boundary

This is a presentation-only hotfix.

It changes no:

- FoxESS control or write authority;
- EV control or EV SOC synchronisation;
- tariff or Intelligent-slot logic;
- optimiser/export policy;
- commissioning behaviour;
- ROI arithmetic; or
- hardware command scope.
