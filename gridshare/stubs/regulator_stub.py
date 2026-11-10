"""STUB for Member 3 - regulator.

Objective (team proposal): maximise local P2P trading of renewable energy,
i.e. reduce what the community imports from the external grid.

Rules:
* mode "none"    : no incentives (price-only baseline).
* mode "fixed"   : constant P2P bonus of 0.02 EUR/kWh paid to sellers,
                   green sellers have priority on equal price,
                   anti-gouging rule: a seller whose ask is more than 20% above
                   its forecast price (or above the absolute cap) is banned
                   from P2P for the next step and must use the aggregator.
* mode "adaptive": like fixed, but the bonus follows a feedback rule on the
                   share of the locally tradable energy that was traded P2P:
                   bonus += 0.025 * (target - observed), clipped to [0, 0.06]
                   EUR/kWh. The bonus is only updated when P2P trading was
                   physically possible (surplus and deficit both > 0), so it
                   does not wind up during the night.
Deterministic: same previous metrics -> same policy.
"""
from __future__ import annotations

from typing import Optional

from ..contract import Policy, SimConfig, StepMetrics

FIXED_BONUS = 0.02
TARGET_P2P_SHARE = 0.95       # of the locally tradable energy
MAX_MARKUP = 0.20
MAX_BONUS = 0.06
GAIN = 0.5 * 0.05

_state = {"bonus": FIXED_BONUS}


def reset() -> None:
    _state["bonus"] = FIXED_BONUS


def price_cap(config: SimConfig) -> float:
    return round(config.grid_retail_price * 0.9, 4)


def get_policy(step: int, previous_metrics: Optional[StepMetrics], config: SimConfig) -> Policy:
    mode = config.regulator_mode
    if mode == "none":
        return Policy(step=step, mode="none", note="price-only baseline")
    banned = sorted(previous_metrics.violators) if previous_metrics else []
    if mode == "fixed":
        bonus = FIXED_BONUS
    elif mode == "adaptive":
        if step == 0 or previous_metrics is None:
            reset()
        elif previous_metrics.tradable_kwh > 0:
            err = TARGET_P2P_SHARE - previous_metrics.p2p_potential_share
            _state["bonus"] = min(MAX_BONUS, max(0.0, _state["bonus"] + GAIN * err))
        bonus = _state["bonus"]
    else:
        raise ValueError(f"unknown regulator mode {mode}")
    return Policy(step=step, mode=mode, p2p_bonus_eur_per_kwh=round(bonus, 5),
                  priority_rule="green_first", banned_prosumers=banned,
                  price_cap_eur_per_kwh=price_cap(config), max_markup=MAX_MARKUP,
                  note=f"target P2P share {TARGET_P2P_SHARE:.0%}" if mode == "adaptive" else "fixed bonus")
