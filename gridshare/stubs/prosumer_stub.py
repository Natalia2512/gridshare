"""STUB for Member 1 - prosumer community, PV/price forecasts, self-balancing.

Synthetic, reproducible profiles (fixed seed):
* PV: bell curve between 06:00 and 19:00, peak at 12:30, scaled by kWp and a
  daily weather factor; forecast = actual * (1 + gaussian error).
* Demand: base load + morning (07-09) and evening (18-22) peaks + noise.
* Price forecast: time-of-use shape, cheap at midday (solar), expensive in
  the evening peak.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional

from ..contract import BEHAVIOUR_TYPES, ProsumerState, SimConfig

_PROFILE_CACHE: Dict = {}


def _profiles(n: int, seed: int) -> List[Dict]:
    key = (n, seed)
    if key not in _PROFILE_CACHE:
        rng = random.Random(seed)
        profiles = []
        for i in range(n):
            has_pv = rng.random() < 0.8                 # 80% prosumers, 20% pure consumers
            profiles.append({
                "prosumer_id": f"P{i + 1:03d}",
                "behaviour": BEHAVIOUR_TYPES[i % len(BEHAVIOUR_TYPES)],
                "pv_kwp": round(rng.uniform(3.0, 6.0), 2) if has_pv else 0.0,
                "base_kw": round(rng.uniform(0.25, 0.5), 3),
                "peak_kw": round(rng.uniform(0.6, 1.4), 3),
            })
        _PROFILE_CACHE[key] = profiles
    return _PROFILE_CACHE[key]


def pv_shape(hour: float) -> float:
    """Normalised PV output (0..1) for a given hour of the day."""
    if hour < 6 or hour > 19:
        return 0.0
    return max(0.0, math.sin(math.pi * (hour - 6) / 13.0)) ** 1.5


def demand_shape(hour: float) -> float:
    morning = math.exp(-((hour - 8.0) ** 2) / 2.0)
    evening = math.exp(-((hour - 20.0) ** 2) / 3.0)
    return morning * 0.7 + evening


def price_forecast(hour: float, cfg: SimConfig) -> float:
    """Forecast local price (EUR/kWh): between feed-in and retail grid prices."""
    lo, hi = cfg.grid_feed_in_price, cfg.grid_retail_price
    base = 0.55 - 0.35 * pv_shape(hour) + 0.35 * demand_shape(hour) / 1.0
    base = min(max(base, 0.0), 1.0)
    return round(lo + (hi - lo) * (0.25 + 0.6 * base) * 0.95, 4)


def simulate_step(step: int, seed: int, prev_state: Optional[List[ProsumerState]],
                  config: SimConfig) -> List[ProsumerState]:
    hour = step % 24 + 0.5
    day = step // 24
    weather_rng = random.Random(seed * 1000 + day)
    weather = weather_rng.uniform(0.75, 1.0) * config.pv_scale
    out: List[ProsumerState] = []
    for prof in _profiles(config.n_prosumers, seed):
        rng = random.Random(f"{seed}-{step}-{prof['prosumer_id']}")
        pv = prof["pv_kwp"] * pv_shape(hour) * weather * rng.uniform(0.9, 1.05)
        pv_fc = max(0.0, pv * (1 + rng.gauss(0, 0.1)))
        demand = prof["base_kw"] + prof["peak_kw"] * demand_shape(hour) * rng.uniform(0.8, 1.2)
        pv, demand, pv_fc = round(pv, 4), round(demand, 4), round(pv_fc, 4)
        self_c = min(pv, demand)
        out.append(ProsumerState(
            prosumer_id=prof["prosumer_id"], step=step, behaviour=prof["behaviour"],
            pv_kwh=pv, demand_kwh=demand, pv_forecast_kwh=pv_fc,
            forecast_price=price_forecast(hour, config),
            self_consumed_kwh=round(self_c, 4),
            surplus_kwh=round(pv - self_c, 4), deficit_kwh=round(demand - self_c, 4),
        ))
    return out
