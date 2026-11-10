# Integration guide for Members 1, 2 and 3

You never need to edit `simulation.py`, `blockchain.py` or the stubs. Add your
module under `gridshare/` with the function signature below, and the simulator
uses it instead of the stub automatically. Run `python run_demo.py --quiet` to check:
after the first scenario it prints `modules used: ... trading=real (gridshare/trading.py) ...`.

| Owner | Create file | Must define | Returns | Stub to start from |
|---|---|---|---|---|
| Member 1 | `gridshare/prosumer.py` | `simulate_step(step, seed, prev_state, config)` | `list[ProsumerState]` (exactly `config.n_prosumers`) | `stubs/prosumer_stub.py` |
| Member 1 | `gridshare/decision.py` | `decide_orders(step, prosumers, config)` | `list[Order]` | `stubs/decision_stub.py` |
| Member 2 | `gridshare/trading.py` | `clear_markets(step, orders, prosumers, policy, config)` | `MarketResult` | `stubs/trading_stub.py` |
| Member 3 | `gridshare/regulator.py` | `get_policy(step, previous_metrics, config)` (+ optional `reset()`) | `Policy` | `stubs/regulator_stub.py` |
| Member 3 | `gridshare/metrics.py` | `evaluate(step, prosumers, orders, market, policy)` | `StepMetrics` | `stubs/metrics_stub.py` |
| Member 3 | `gridshare/charts.py` | `make_charts(results_by_scenario, out_dir)` | `list[str]` (file paths) | `stubs/charts_stub.py` |

All types are in `gridshare/contract.py`. Units: 1 step = 1 hour, kWh, EUR/kWh.

## Rules checked automatically at every step

**Member 1**
* exactly 100 prosumers (`n_prosumers`), unique IDs, `behaviour` in `conservative | aggressive | green`
* no negative values; never surplus and deficit at the same time
* `self_consumed + surplus == pv` and `self_consumed + deficit == demand`
* orders: quantity > 0, never more than that prosumer's surplus (SELL) or deficit (BUY)

**Member 2**
* every transaction: quantity > 0, price ≥ 0, buyer ≠ seller, unique ID
* `market_type`: `P2P` (between two prosumers) or `LOCAL` (one side must be `"AGGREGATOR"`)
* P2P quantity never exceeds what was offered or requested in the orders
* P2P price lies between the seller's ask minus the regulator bonus and the buyer's bid
* buyer and seller are known prosumer IDs or `"AGGREGATOR"`; all numbers are finite (no NaN)
* banned prosumers (`policy.banned_prosumers`) never trade P2P
* every surplus and deficit is fully settled, P2P + LOCAL; whatever is not traded P2P goes to the aggregator
* `residual_import - residual_export == local buys - local sells`

**Member 3**
* `get_policy` returns a `Policy` with the right step, mode in `none | fixed | adaptive`,
  bonus >= 0, `priority_rule` in `price | green_first`; `evaluate` returns `StepMetrics`
* the policy must be deterministic for the same `previous_metrics`
* the regulator must change trading (bonus, priority, bans), not only display a score

## Developing without the others

Each member works against the example files and does not need the other modules:

```python
from gridshare.fixtures import load_prosumers, load_orders, load_policy, load_previous_metrics
from gridshare.contract import SimConfig, validate_market
from gridshare.trading import clear_markets   # your module

ps, orders, policy = load_prosumers(), load_orders(), load_policy()
market = clear_markets(12, orders, ps, policy, SimConfig())
validate_market(market, orders, ps, policy, 12)   # raises ContractError if something is wrong
```

The tests in `tests/test_stubs.py` are the acceptance tests for your module. Point
them at your module and make sure they pass before opening the pull request.

## Workflow

1. Create a branch: `git checkout -b m2-trading`
2. Commit small pieces; open a pull request with one sample output file and tests
3. CI must be green, and one teammate reviews (M2 reviews M1, M3 reviews M2, M4 reviews M3, M1 reviews M4)
4. Merge. Main must always run: `pytest -q && python run_demo.py --scenario all --quiet`

Changing `contract.py` requires agreement from the whole team and a new `CONTRACT_VERSION`.
