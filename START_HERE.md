# Start here — KEMS 0.7.0-alpha6 scenario comparison

Alpha6 builds on the proven alpha5 no-export/live-readiness behaviour and adds a parallel **What would today have looked like?** replay engine. The active KEMS strategy is not changed by comparison replay.

## Development branch

```text
release/0.7.0-alpha6-scenario-comparison
```

Create the branch from the latest `develop`, apply the alpha6 overlay/patch, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check .
python -m pytest
python -m pre_commit run --all-files
```

The supplied build passes **136 pytest tests** before local Black/Ruff execution.

## New comparison scenarios

KEMS now replays the same retained demand and tariff observations through:

1. No system — grid supplies the whole home.
2. Solar only — solar self-consumption plus paid surplus export, no battery.
3. Solar + battery — conventional tariff-unaware self-use, no grid charging.
4. KEMS no-export — solar-aware cheap charging and self-use with deliberate export disabled.
5. Full KEMS smart control — paid export, cheap charging, home reserve, paced battery export and Power Down optimisation.

Today, Yesterday, 7-day and 30-day summaries are exposed. The Today payload also includes a replay timeline for cumulative-cost graphs. Daily standing charge is included in scenario total cost; it cancels out when comparing savings.

## Dashboards

- `dashboards/kems_compare_builtin.yaml` — standard Home Assistant cards only.
- `dashboards/kems_compare_advanced.yaml` — full replay graphs using ApexCharts plus Mushroom summary cards.

The advanced dashboard needs **ApexCharts Card** and **Mushroom** from HACS.

## Safety

Alpha6 remains simulation/shadow only. Real FoxESS writes are still hard-blocked until the commissioned backend is mapped and verified.
