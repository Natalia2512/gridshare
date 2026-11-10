# GridShare 100 – P2P energy trading simulator

Smart Grids course project (Politecnico di Torino). A community of 100 prosumers
balances its energy in three stages every hour (self-balancing → bilateral P2P
negotiation → local market through the load aggregator), guided by a regulator,
with every agreed trade recorded on a Proof-of-Stake blockchain with 10+ validators.

> **Status of this version (Member 4):** blockchain, simulation controller, demo,
> tests and CI are complete. The modules of Members 1–3 are currently **stubs**
> (`gridshare/stubs/`), so the whole pipeline already runs end to end. When the
> real modules are added they are used automatically. See `INTEGRATION.md`.

## Where to write your code (team)

Create your module **directly in `gridshare/`**, with exactly this name:

| Member | File(s) to create |
|---|---|
| Member 1 | `gridshare/prosumer.py`, `gridshare/decision.py` |
| Member 2 | `gridshare/trading.py` |
| Member 3 | `gridshare/regulator.py`, `gridshare/metrics.py`, `gridshare/charts.py` |

The quickest start: copy the matching file from `gridshare/stubs/`
(e.g. `stubs/trading_stub.py` → `gridshare/trading.py`), keep the function
signature, and replace the logic with yours. The simulator then uses your file
automatically instead of the stub; check the "modules used" line printed by
`python run_demo.py --quiet`.

**Fix the imports in the copied file.** The file moves up one folder, so the
relative imports lose one dot:

    from ..contract import ...   →   from .contract import ...

If you forget, the run stops immediately with an `ImportError`.

Do not edit `gridshare/stubs/`. Read `INTEGRATION.md` for the rules your output
must satisfy.

## 1. Setup

Requires Python 3.9 or newer.

```bash
python -m venv .venv
# Windows (cmd):         .venv\Scripts\activate
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
#   (if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned)
# macOS/Linux:           source .venv/bin/activate
pip install -r requirements.txt
```

The simulator itself uses only the Python standard library. `matplotlib` is only
needed for the charts, and `pytest` only for the tests.

## 2. Run

```bash
python run_demo.py                        # adaptive regulator, 24 steps, prints every step
python run_demo.py --scenario all         # baseline, fixed, adaptive, pv_shortage + comparison table
python run_demo.py --scenario baseline --steps 48 --seed 7
python run_demo.py --faulty-validators 2  # 2 of 10 validators refuse to sign: blocks still exceed the 2/3 quorum
python run_demo.py --use-stubs            # ignore real modules, run stubs only
python run_demo.py --help
```

Outputs go to `results/<scenario>/`:

| File | Content |
|---|---|
| `steps.csv` | metrics for every time step (PV, demand, P2P/LOCAL kWh, tradable kWh, grid import, energy cost, bonus, banned, block hash) |
| `transactions.csv` | every agreed trade (P2P and LOCAL) |
| `ledger.json` | the full blockchain: validators, stakes, blocks, signatures |
| `summary.json` | totals, checks, which modules were real or stubs |
| `../comparison.csv` | one row per scenario (with `--scenario all`) |
| `../charts/*.png` | comparison charts |

At the end of each scenario the demo prints the automatic checks: chain valid,
every agreed trade on chain, tamper test (one recorded trade is modified in a
copy of the chain and the change is detected), energy balance. The comparison
table shows the key regulator indicator, **P2P / tradable**: the share of the
energy that *could* be traded between neighbours (min of total surplus and total
deficit) that actually *was* traded P2P. Wrong arguments (fewer than 24 steps,
fewer than 10 validators, ...) stop with a short error message.

## 3. Tests

```bash
pytest -q
```

67 tests: blockchain (validators, hashing, signatures, quorum, proposer and stake
history, tampering, truncation, malformed/NaN/invalid/double-spent trades),
interface contract, stubs, CLI, and full 24-step runs of all scenarios.
GitHub Actions (`.github/workflows/ci.yml`) runs the tests and the full
simulation on every push and pull request, on Linux and Windows.

## 4. Scenarios

| Scenario | Regulator | PV |
|---|---|---|
| `baseline` | none (price-only) | 100% |
| `fixed` | fixed P2P bonus, green-first priority, anti-gouging ban | 100% |
| `adaptive` | bonus adjusted every step towards a P2P target, same rules | 100% |
| `pv_shortage` | adaptive | 30% (stress test) |

## 5. Architecture

```
gridshare/
  contract.py      shared data types + validation (frozen interface, all members)
  blockchain.py    Member 4 – PoS ledger
  simulation.py    Member 4 – 24-step controller, scenario configs, output writer
  fixtures.py      loaders for example_inputs/ and example_outputs/
  stubs/           temporary stand-ins for Members 1-3
run_demo.py        Member 4 – CLI / live demo
tools/make_fixtures.py   regenerates the example files
tests/             pytest suite
```

Order of operations in every step (`simulation.py`):

1. **Prosumers** (M1): PV, demand, forecasts, self-balancing → surplus or deficit
2. **Regulator** (M3): policy for this step, based on the previous step's metrics
3. **Decisions** (M1): each prosumer sets quantity and limit price (bid/ask)
4. **Trading** (M2): P2P matching, then the residual goes to the local market via `AGGREGATOR`
5. **Blockchain** (M4): one block per step containing every agreed trade
6. **Metrics** (M3): KPIs for the step, fed back to the regulator

Every hand-over is checked against `contract.py`. If a module breaks the interface,
the run stops with a clear `ContractError`.

## 6. Blockchain (Member 4)

* **Validators:** at least 10 (configurable), each with a stake and a secret signing key
  generated with the OS secure random generator.
* **Proposer:** chosen by stake-weighted random selection among the honest validators,
  seeded with the previous block hash, so block hashes are reproducible.
* **Block content:** every P2P and LOCAL trade of the step, the SHA-256 Merkle root of
  those trades, the link to the previous block and a snapshot of the stakes. A block is
  produced even when a step has no trades.
* **Validation:** each validator re-checks the trade rules (positive quantity,
  non-negative price, buyer ≠ seller, LOCAL trades must involve the aggregator, no
  duplicates or double spends), the Merkle root, the previous-block link and the block
  hash. It then signs with HMAC-SHA256.
* **Finality:** a block is final once validators holding **more than 2/3** of the stake
  have signed. The proposer earns a small stake reward. With 10 validators, 2 faulty ones
  are always tolerated; with 3 it depends on how the stake is distributed (seed).
* **Audit:** `verify_chain()` recomputes every hash, Merkle root, link, signature and
  quorum, re-checks that each proposer was the correct stake-weighted choice and that
  the stakes evolved correctly, and compares the chain length and tip with what the
  simulation recorded. Any modification made without the validators' secret keys is detected.

## 7. Notes for the team

* With the stub data there is no battery or demand flexibility, so the community's
  **net grid import is physically fixed** (total demand − total PV). The regulator
  changes *how* energy is traded (P2P vs aggregator, prices, who may trade), not the
  total import. To make the regulator reduce imports, Member 1 would need to add a
  battery or flexible loads. This is optional.
* Stub parameters such as the bonus, target and price markups are placeholders.
  Member 3 should tune them in the real regulator.
