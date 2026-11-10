#!/usr/bin/env python3
"""Regenerate example_inputs/ and example_outputs/ from the stub pipeline.

Run from the repository root:  python tools/make_fixtures.py
Step 12 (midday, PV surplus) under the adaptive scenario is used, because it
contains P2P trades, LOCAL trades and banned prosumers.
Note: validator keys are random, so the signatures in block_step12.json change
every time; everything else is identical for the same seed.
"""
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gridshare.blockchain import Blockchain  # noqa: E402
from gridshare.fixtures import FIXTURE_STEP, INPUTS, OUTPUTS  # noqa: E402
from gridshare.simulation import config_for, load_modules  # noqa: E402


def dump(folder, name, obj):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    print("wrote", os.path.relpath(os.path.join(folder, name)))


def main():
    cfg = config_for("adaptive", use_stubs=True)
    f, mods, _ = load_modules(use_stubs=True)
    mods["regulator"].reset()
    chain = Blockchain(cfg.n_validators, cfg.seed)
    prev_state = prev_metrics = None
    for step in range(FIXTURE_STEP + 1):
        prosumers = f["prosumer"](step, cfg.seed, prev_state, cfg)
        policy = f["regulator"](step, prev_metrics, cfg)
        orders = f["decision"](step, prosumers, cfg)
        market = f["trading"](step, orders, prosumers, policy, cfg)
        block = chain.append_transactions(step, market.transactions)
        metrics = f["metrics"](step, prosumers, orders, market, policy)
        metrics.block_hash, metrics.block_validators = block.block_hash, len(block.validator_ids)
        if step == FIXTURE_STEP - 1:
            dump(INPUTS, f"metrics_step{step}.json", asdict(metrics))
        prev_state, prev_metrics = prosumers, metrics
    dump(INPUTS, f"prosumers_step{FIXTURE_STEP}.json", [asdict(p) for p in prosumers])
    dump(INPUTS, f"orders_step{FIXTURE_STEP}.json", [asdict(o) for o in orders])
    dump(INPUTS, f"policy_step{FIXTURE_STEP}.json", asdict(policy))
    dump(OUTPUTS, f"market_step{FIXTURE_STEP}.json", asdict(market))
    dump(OUTPUTS, f"metrics_step{FIXTURE_STEP}.json", asdict(metrics))
    dump(OUTPUTS, f"block_step{FIXTURE_STEP}.json", chain.chain[-1].to_dict())
    print(f"block #{block.block_index}: {block.n_transactions} transactions, {len(block.validator_ids)} signatures")


if __name__ == "__main__":
    main()
