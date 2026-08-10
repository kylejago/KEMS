# Start here — KEMS 0.7.0-alpha5 no-export live readiness

Alpha5 builds on the released/reconciled alpha4 baseline. It adds an explicit **Export tariff status** and a safe **Not active / awaiting export tariff** policy for the period after installation but before a paid export tariff is live.

## Development branch

```text
release/0.7.0-alpha5-no-export-live-readiness
```

Create it from the latest `develop`, apply the supplied patch, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

Expected pytest result from the supplied build: `129 passed` before any formatter-only changes.

Commit:

```text
feat: add awaiting export tariff mode
```

After installing in Home Assistant, restart and open:

```text
Settings → Devices & services → KEMS → Configure → Tariff and prices
```

Set **Export tariff status** to **Not active / awaiting export tariff** to test the new policy. KEMS should then report a 0p/kWh effective export rate, no deliberate battery/grid export, self-use planning, solar-to-battery charging, and a solar-aware overnight target during a confirmed cheap period.

Real FoxESS writes remain blocked in alpha5.
