# Full KEMS Agile forecast arbitrage

This post-Alpha8 behavioural slice reconciles three planning rules without
changing the frozen Alpha7.52 compatibility runtimes or enabling hardware writes.

## Effective pre-cheap SOC floor

The live rolling and deadline plan must use the higher of:

- the normal KEMS pre-cheap target (normally 10%); and
- `ForecastPlanState.minimum_precheap_soc_percent` when the forecast plan is ready.

The forecast value exists specifically to retain enough stored energy at the
start of the configured overnight cheap window for the available charging power
and window length to reach the next morning's forecast requirement.

## Ordinary export economic floor

Full KEMS Agile does not deliberately export battery energy in an Agile slot
priced below the configured overnight import rate. The overnight rate is the
ordinary replacement-price floor; house demand remains first priority.

This is intentionally a policy floor rather than a battery-wear hurdle. The
normal objective remains to use cheap overnight energy and sell otherwise-safe
battery energy into better outgoing prices.

## Forecast solar headroom

A high-confidence hourly solar forecast can indicate that the battery will fill
before later solar arrives. KEMS may then move already-planned battery export into
an earlier outgoing slot when:

- forecast confidence is at least 70%;
- the battery is projected to spill solar after respecting the effective
  pre-cheap SOC floor and a conservative house-load allowance;
- the earlier slot is at or above the overnight replacement-price floor; and
- the earlier slot is at least 0.15 p/kWh better than the best outgoing price
  expected during the projected spill period.

The headroom operation is deliberately bounded: it only re-times battery export
that was already in the rolling plan. It does not increase the day's planned
battery export because sunshine is forecast, does not reduce protected reserve
or house energy, and is recalculated on every normal KEMS coordinator scan.

This means a pattern such as an earlier 12.94 p/kWh outgoing slot followed by a
forecast battery-saturation period around 9 p/kWh can create battery headroom
before the solar arrives, while a weaker earlier price will simply leave the
existing plan unchanged.

## Safety boundary

This remains simulation/shadow behaviour only. There are no Home Assistant
hardware-control service calls, no FoxESS write backend, no commissioning bypass,
and real hardware writes remain blocked.
