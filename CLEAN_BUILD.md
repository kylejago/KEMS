# KEMS preserved-history upgrade 0.6.0-alpha5

This is not a clean-history release. It deliberately keeps the existing `clean_v6_alpha2` observation namespace so collected learning data continues without interruption.

The simulated financial ledger has its own migration version. On the first alpha5 startup, alpha4 simulated value resets because joined Power Down sessions can change battery timing and add a separate Octopoints bonus. Observed history, mappings, gas data, and actual post-install totals remain untouched.
