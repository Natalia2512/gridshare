"""STUB for Member 1 - prosumer decision model (bid/ask price and quantity).

Every prosumer offers its whole surplus (SELL) or asks for its whole deficit
(BUY). The limit price depends on the behaviour type and on the forecast
price:
    conservative: sells at +5%  of forecast, buys up to  -5%
    aggressive  : sells at +25% of forecast, buys up to -15%
    green       : sells at -5%  of forecast, buys up to +10% (values local PV)
A deterministic small noise makes the order book realistic.
"""
from __future__ import annotations

import random
from typing import List

from ..contract import SIDE_BUY, SIDE_SELL, Order, ProsumerState, SimConfig

SELL_FACTOR = {"conservative": 1.05, "aggressive": 1.25, "green": 0.95}
BUY_FACTOR = {"conservative": 0.95, "aggressive": 0.85, "green": 1.10}
MIN_QTY = 0.0


def decide_orders(step: int, prosumers: List[ProsumerState], config: SimConfig) -> List[Order]:
    orders: List[Order] = []
    for p in prosumers:
        rng = random.Random(f"order-{config.seed}-{step}-{p.prosumer_id}")
        noise = rng.uniform(0.97, 1.03)
        if p.surplus_kwh > MIN_QTY:
            price = max(config.grid_feed_in_price, p.forecast_price * SELL_FACTOR[p.behaviour] * noise)
            orders.append(Order(f"O-{step:03d}-{p.prosumer_id}-S", step, p.prosumer_id, SIDE_SELL,
                                p.surplus_kwh, round(price, 4), p.behaviour))
        elif p.deficit_kwh > MIN_QTY:
            price = min(config.grid_retail_price, p.forecast_price * BUY_FACTOR[p.behaviour] * noise)
            orders.append(Order(f"O-{step:03d}-{p.prosumer_id}-B", step, p.prosumer_id, SIDE_BUY,
                                p.deficit_kwh, round(price, 4), p.behaviour))
    return orders
