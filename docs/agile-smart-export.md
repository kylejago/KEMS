# Agile Smart Export — current Alpha8 behaviour

Agile Smart Export is KEMS' export-price-aware strategy for Octopus Agile Outgoing. It compares and plans against real half-hour prices while retaining the same house-demand, battery-reserve, solar and inverter constraints used by the wider KEMS digital twin.

Alpha8.0 is a refactor/parity release. Its Agile behaviour baseline is the proven `0.7.0-alpha7.52` stack, preserved behind one frozen compatibility boundary while future work moves into canonical modules. Real FoxESS hardware writes remain blocked until commissioning passes.

## Price collection

KEMS discovers the active Agile Outgoing product and tariff through the public Octopus API rather than hard-coding one product code. Rates retain their real `valid_from`/`valid_to` timestamps and the horizon logic is UK/DST aware.

When a relevant future period is absent, KEMS retries the exact target period and records recovery evidence. It never invents a neighbour price or substitutes zero as a price.

## Known prices and incomplete horizons

KEMS distinguishes a verified clean Octopus publication gap from a retrieval failure.

For a **verified publication gap**, KEMS may continue planning with the real prices already published. The current settlement period must still have a genuine price before deliberate export is permitted. Unpublished future slots receive no guessed export command. The Alpha7.46–Alpha7.52 no-reserve path keeps **0 kWh** artificially reserved for those clean unpublished slots and re-ranks the economic plan when new prices appear.

For **retrieval ambiguity or failure**, KEMS remains conservative. A network/API failure, unverified gap or missing current price cannot be promoted into the no-reserve path.

Tomorrow's partially published price horizon follows the same principle. A clean progressive horizon can report and plan against the published prices without inventing a reserve; genuine retrieval errors remain conservative. Tiny reporting-only residuals at or below the established tolerance are normalised so a fully covered plan reports 100% coverage rather than a misleading 0.001 kWh gap.

## Dispatch priorities

Outside configured cheap import periods:

1. solar serves the house first;
2. battery can serve remaining house demand above the protected reserve;
3. deliberate battery export uses the highest-value eligible Agile periods;
4. deadline protection may move required export earlier when the target would otherwise become physically unreachable;
5. clean newly published prices trigger re-ranking rather than receiving a guessed value beforehand.

Power Down and Happy Hour keep their established priority ordering above ordinary Agile price optimisation, with independent safety remaining authoritative.

The current live house-demand basis is the same KEMS live house-load source used by the Live dashboard. Digital-twin demand remains separate replay/parity evidence rather than being presented as physical live data.

## Solar-aware inverter headroom

The inverter constraint is applied to total AC output, not battery power in isolation.

KEMS calculates routed solar AC first, then gives the battery only the remaining configured inverter headroom. A deliberate export candidate therefore satisfies:

`solar AC + battery AC <= configured inverter limit`

At full battery SOC, surplus solar that cannot charge the battery remains eligible for export within the inverter and site export limits rather than being incorrectly routed back into battery charging.

## Deadline and plan reconciliation

KEMS works backwards from the next cheap-period deadline using the solar-aware physical discharge capacity. The latest-safe-start guard prevents a profitable-looking later plan from making the target SOC physically unreachable.

When deadline protection forces current export, that energy replaces the lowest-value later selected export rather than being added on top of the day's economic target. Maximum-discharge escalation uses the same equal-energy reconciliation so the rolling plan and the physical deadline decision remain consistent.

## Shadow command and non-zero proof

The optimiser's exact candidate is translated into the inverter-shaped shadow command. Deliberate export requires the established export-capable mode and grid-export permission; non-export operation keeps its normal self-use behavior.

The independent safety layer checks 13 command invariants including charge/discharge exclusivity, configured charge/discharge/export/inverter limits, minimum SOC and the hardware-write lock.

A genuine non-zero export proof applies that exact safe candidate to a one-step digital-twin routing replay. It requires, among the retained checks:

- a genuine non-zero optimiser export target;
- command/optimiser parity;
- a qualified price state;
- export permission;
- 13/13 independent safety;
- strict target/outcome parity;
- configured discharge/inverter/SOC limits respected;
- hardware writes still blocked.

## Runtime consolidation

Alpha8.0 does not discard the proven Alpha7.52 implementation before parity is established. Instead, the historical installer sequence is frozen in `agile_alpha7_compat.py` and entered through one compatibility boundary from the canonical Agile runtime entry point.

Regression coverage verifies that the frozen installers remain complete/resolvable and prohibits new `agile_alpha8*.py` version-named patch modules. New Alpha8 behavior should be implemented in canonical modules once parity work is complete.

## Web and panel

KEMS Web `0.8.0-alpha8-web.0` preserves the accepted Web.33 property PWA: read-only telemetry, authenticated Cloudflare Access manifest loading, install diagnostics and service-worker cache guards. The Agile web page remains a reporting surface and cannot call Home Assistant services.

The managed ESPHome panel is `0.8.0-alpha8-panel.0`. It consumes the final coherent current-routing snapshot and the packaged YAML version is now authoritative; Home Assistant no longer rewrites one panel release string into another at runtime.

## Safety boundary

Agile Smart Export remains subject to commissioning gates before physical FoxESS control is enabled. Alpha8.0 does not relax hardware-write permissions, site/inverter limits, minimum SOC, sign-convention verification or the independent safety validator.

The public `kems.uk` website has no property-control path, and remote property access does not expose Home Assistant or Pi-management services.
