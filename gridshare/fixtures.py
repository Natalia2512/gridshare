"""Load the shared example files (example_inputs/, example_outputs/) as contract objects.

Every member can develop and test against these files without waiting for the
other modules, e.g. Member 2:

    from gridshare.fixtures import load_prosumers, load_orders, load_policy
    prosumers = load_prosumers(); orders = load_orders(); policy = load_policy()
    result = clear_markets(12, orders, prosumers, policy, SimConfig())

Regenerate the files with:  python tools/make_fixtures.py
"""
from __future__ import annotations

import json
import os
from typing import List

from .contract import MarketResult, Order, Policy, ProsumerState, StepMetrics, Transaction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS = os.path.join(ROOT, "example_inputs")
OUTPUTS = os.path.join(ROOT, "example_outputs")
FIXTURE_STEP = 12


def _load(folder: str, name: str):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return json.load(f)


def load_prosumers() -> List[ProsumerState]:
    return [ProsumerState(**d) for d in _load(INPUTS, f"prosumers_step{FIXTURE_STEP}.json")]


def load_orders() -> List[Order]:
    return [Order(**d) for d in _load(INPUTS, f"orders_step{FIXTURE_STEP}.json")]


def load_policy() -> Policy:
    return Policy(**_load(INPUTS, f"policy_step{FIXTURE_STEP}.json"))


def load_previous_metrics() -> StepMetrics:
    return StepMetrics(**_load(INPUTS, f"metrics_step{FIXTURE_STEP - 1}.json"))


def load_market() -> MarketResult:
    d = _load(OUTPUTS, f"market_step{FIXTURE_STEP}.json")
    d["transactions"] = [Transaction(**t) for t in d["transactions"]]
    return MarketResult(**d)


def load_metrics() -> StepMetrics:
    return StepMetrics(**_load(OUTPUTS, f"metrics_step{FIXTURE_STEP}.json"))
