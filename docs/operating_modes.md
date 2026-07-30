# Analysis strategies

KEMS 0.3 contains analysis strategies, not control modes.

## Export first

During cheap periods, the simulation powers the house from the grid and charges the battery. Outside cheap periods, it exports solar and uses the simulated battery for house load before allowing residual grid import. This reflects Kyle's planned tariff-arbitrage policy.

## Solar self-use first

Outside cheap periods, solar supplies house load first. Surplus solar is exported, and the battery supplies remaining load before residual grid import.

Both strategies are simulations only.

## Confirmed cheap periods

KEMS treats normal Octopus off-peak as cheap. An extra Intelligent dispatch slot is confirmed only when the Octopus slot is active and Ohme reports that the EV is charging.
