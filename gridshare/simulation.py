"""Member 4 - simulation controller (orchestration of all modules).

Order of operations in every time step (as required by the course):
    1. Member 1  prosumers: PV/demand/forecasts + SELF-BALANCING
    2. Member 3  regulator: policy for this step (uses previous step metrics)
    3. Member 1  decisions: each prosumer sets quantity and price (bid/ask)
    4. Member 2  P2P negotiation, then LOCAL market through the aggregator
    5. Member 4  every agreed transaction is written to the PoS blockchain
    6. Member 3  metrics for the step (fed back to the regulator)
Every hand-over is validated against gridshare/contract.py, so a broken
interface fails immediately with a clear message.

Module loading: if a real module exists (e.g. gridshare/trading.py) it is
used; otherwise the stub in gridshare/stubs/ is used. Force stubs with
SimConfig(use_stubs=True) or `python run_demo.py --use-stubs`.
"""
from __future__ import annotations

import csv
import importlib
import json
import os
from dataclasses import asdict, replace
from typing import Callable, Dict, List, Optional, Tuple

from . import contract as C
from .blockchain import Blockchain

# module name -> (function name, stub module)
MODULES: Dict[str, Tuple[str, str]] = {
    "prosumer": ("simulate_step", "gridshare.stubs.prosumer_stub"),
    "decision": ("decide_orders", "gridshare.stubs.decision_stub"),
    "regulator": ("get_policy", "gridshare.stubs.regulator_stub"),
    "trading": ("clear_markets", "gridshare.stubs.trading_stub"),
    "metrics": ("evaluate", "gridshare.stubs.metrics_stub"),
    "charts": ("make_charts", "gridshare.stubs.charts_stub"),
}

SCENARIOS: Dict[str, Dict] = {
    "baseline": {"regulator_mode": "none", "pv_scale": 1.0},
    "fixed": {"regulator_mode": "fixed", "pv_scale": 1.0},
    "adaptive": {"regulator_mode": "adaptive", "pv_scale": 1.0},
    "pv_shortage": {"regulator_mode": "adaptive", "pv_scale": 0.3},
}


def config_for(scenario: str, **overrides) -> C.SimConfig:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    cfg = C.SimConfig(scenario=scenario, **SCENARIOS[scenario])
    return replace(cfg, **overrides)


def load_modules(use_stubs: bool = False) -> Tuple[Dict[str, Callable], Dict[str, object], Dict[str, str]]:
    funcs: Dict[str, Callable] = {}
    mods: Dict[str, object] = {}
    sources: Dict[str, str] = {}
    for name, (fn, stub) in MODULES.items():
        mod = None
        if not use_stubs:
            try:
                mod = importlib.import_module(f"gridshare.{name}")
                sources[name] = f"real (gridshare/{name}.py)"
            except ModuleNotFoundError as e:
                if e.name != f"gridshare.{name}":
                    raise          # the real module exists but one of ITS imports is missing
                mod = None
        if mod is None:
            mod = importlib.import_module(stub)
            sources[name] = f"stub ({stub.replace('.', '/')}.py)"
        if not hasattr(mod, fn):
            raise C.ContractError(f"{mod.__name__} must define {fn}()")
        funcs[name] = getattr(mod, fn)
        mods[name] = mod
    return funcs, mods, sources


def run_simulation(config: C.SimConfig, log: Optional[Callable[[str], None]] = None) -> C.SimulationResult:
    if config.n_steps < 24:
        raise ValueError("the course requires at least 24 time steps")
    funcs, mods, sources = load_modules(config.use_stubs)
    if hasattr(mods["regulator"], "reset"):
        mods["regulator"].reset()

    chain = Blockchain(n_validators=config.n_validators, seed=config.seed,
                       faulty_validators=config.faulty_validators)
    prev_state: Optional[List[C.ProsumerState]] = None
    prev_metrics: Optional[C.StepMetrics] = None
    metrics: List[C.StepMetrics] = []
    blocks: List[C.BlockResult] = []
    all_tx: List[C.Transaction] = []
    energy_ok = True

    for step in range(config.n_steps):
        # 1. prosumers + self-balancing
        prosumers = funcs["prosumer"](step, config.seed, prev_state, config)
        C.validate_prosumers(prosumers, config.n_prosumers, step)
        # 2. regulator policy
        policy = funcs["regulator"](step, prev_metrics, config)
        C.validate_policy(policy, step)
        # 3. prosumer decisions
        orders = funcs["decision"](step, prosumers, config)
        C.validate_orders(orders, prosumers, step)
        # 4. P2P + local market
        market = funcs["trading"](step, orders, prosumers, policy, config)
        C.validate_market(market, orders, prosumers, policy, step)
        # 5. blockchain
        block = chain.append_transactions(step, market.transactions)
        # 6. metrics
        m = funcs["metrics"](step, prosumers, orders, market, policy)
        C.validate_metrics(m, step)
        m.block_hash = block.block_hash
        m.block_validators = len(block.validator_ids)

        pv = sum(p.pv_kwh for p in prosumers)
        demand = sum(p.demand_kwh for p in prosumers)
        if not abs(pv + market.residual_import_kwh - market.residual_export_kwh - demand) <= 1e-3:
            energy_ok = False
            if log:
                log(f"step {step:02d} | WARNING energy balance broken: PV + import - export != demand")

        metrics.append(m)
        blocks.append(block)
        all_tx.extend(market.transactions)
        prev_state, prev_metrics = prosumers, m
        if log:
            log(f"step {step:02d} | PV {pv:7.2f} kWh | demand {demand:7.2f} kWh | "
                f"P2P {m.p2p_kwh:6.2f} kWh ({m.n_p2p_trades:3d} trades) | "
                f"LOCAL {m.local_buy_kwh + m.local_sell_kwh:6.2f} kWh | bonus "
                f"{policy.p2p_bonus_eur_per_kwh:.3f} | banned {len(policy.banned_prosumers):2d} | "
                f"block #{block.block_index} {block.block_hash[:10]}.. by {block.proposer_id} "
                f"({len(block.validator_ids)} sig.)")

    chain_ok, chain_errors = chain.verify_chain(expected_blocks=blocks)
    on_chain = chain.transaction_ids() == {t.transaction_id for t in all_tx}
    return C.SimulationResult(config=config, metrics=metrics, blocks=blocks, chain_valid=chain_ok,
                              chain_errors=chain_errors, all_trades_on_chain=on_chain,
                              module_sources=sources, energy_balance_ok=energy_ok,
                              transactions=all_tx, ledger=chain)


def summarise(result: C.SimulationResult) -> Dict:
    ms = result.metrics
    tot = lambda k: round(sum(getattr(m, k) for m in ms), 3)
    traded = tot("p2p_kwh") + tot("local_buy_kwh") + tot("local_sell_kwh")
    return {
        "scenario": result.config.scenario,
        "regulator_mode": result.config.regulator_mode,
        "steps": len(ms),
        "prosumers": result.config.n_prosumers,
        "validators": result.config.n_validators,
        "total_pv_kwh": tot("total_pv_kwh"),
        "total_demand_kwh": tot("total_demand_kwh"),
        "p2p_kwh": tot("p2p_kwh"),
        "p2p_share": round(tot("p2p_kwh") / traded, 4) if traded else 0.0,
        "tradable_kwh": tot("tradable_kwh"),
        "p2p_of_tradable": round(tot("p2p_kwh") / tot("tradable_kwh"), 4) if tot("tradable_kwh") else 0.0,
        "grid_import_kwh": tot("grid_import_kwh"),
        "grid_export_kwh": tot("grid_export_kwh"),
        "community_cost_eur": tot("community_cost_eur"),
        "regulator_bonus_eur": tot("regulator_bonus_eur"),
        "prosumer_net_cost_eur": round(tot("community_cost_eur") - tot("regulator_bonus_eur"), 3),
        "n_banned_total": sum(m.n_banned for m in ms),
        "n_p2p_trades": sum(m.n_p2p_trades for m in ms),
        "n_local_trades": sum(m.n_local_trades for m in ms),
        "n_transactions_on_chain": len(result.ledger.transaction_ids()) if result.ledger else 0,
        "n_blocks": len(result.blocks),
        "chain_valid": result.chain_valid,
        "all_trades_on_chain": result.all_trades_on_chain,
        "energy_balance_ok": result.energy_balance_ok,
    }


def write_outputs(result: C.SimulationResult, out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "steps": os.path.join(out_dir, "steps.csv"),
        "transactions": os.path.join(out_dir, "transactions.csv"),
        "ledger": os.path.join(out_dir, "ledger.json"),
        "summary": os.path.join(out_dir, "summary.json"),
    }
    rows = [asdict(m) for m in result.metrics]
    for r in rows:
        r["violators"] = " ".join(r["violators"])
    with open(paths["steps"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(paths["transactions"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(result.transactions[0])) if result.transactions
                           else ["transaction_id"])
        w.writeheader()
        w.writerows(asdict(t) for t in result.transactions)
    with open(paths["ledger"], "w", encoding="utf-8") as f:
        json.dump(result.ledger.to_json(), f, indent=1)
    with open(paths["summary"], "w", encoding="utf-8") as f:
        json.dump({**summarise(result), "module_sources": result.module_sources,
                   "chain_errors": result.chain_errors}, f, indent=2)
    return paths


def make_charts(results: Dict[str, List[C.StepMetrics]], out_dir: str, use_stubs: bool = False) -> List[str]:
    funcs, _, _ = load_modules(use_stubs)
    return funcs["charts"](results, out_dir)
