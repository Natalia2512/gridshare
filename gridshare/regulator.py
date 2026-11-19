"""Member 3 - adaptive regulator for GridShare 100.

Primary objective
-----------------
Maximise the share of *locally tradable* energy that is exchanged through P2P
trading instead of being routed through the aggregator.

Why this objective is used instead of "minimise grid import": without storage or
flexible demand, net grid import is fixed by total demand minus total PV. The
regulator can change who trades locally, the effective P2P price, and access to
P2P trading, but it cannot change the physical demand/PV balance.

Policies
--------
* ``none``: baseline, price-only trading; no bonus, bans, or special priority.
* ``fixed``: constant P2P seller bonus, green-first tie-breaking, and a one-step
  anti-gouging ban based on violations detected in the previous step.
* ``adaptive``: same rules as fixed, but the P2P bonus is updated from the
  previous step's P2P utilisation using a bounded proportional feedback rule.

The adaptive rule is deterministic and stateless: the next bonus is computed
directly from the previous step's P2P-utilisation error. This avoids hidden
controller state and still responds correctly when the previous P2P volume was
zero.
"""
from __future__ import annotations

from typing import Optional

from .contract import Policy, SimConfig, StepMetrics

# A deliberately modest fixed incentive. The adaptive policy is expected to
# increase it when P2P utilisation falls below target and reduce it otherwise.
FIXED_BONUS = 0.0125  # EUR/kWh
TARGET_P2P_SHARE = 0.90
ADAPTIVE_GAIN = 0.05  # EUR/kWh per unit of utilisation error
MAX_BONUS = 0.06      # hard budget/safety cap, EUR/kWh

# Anti-gouging safeguards. A seller that violates either rule in step t is
# excluded from P2P trading in step t+1 (but can still use the aggregator).
MAX_MARKUP = 0.20
PRICE_CAP_FACTOR = 0.90
EPS = 1e-9


def reset() -> None:
    """Compatibility hook used by the simulator before each scenario.

    The real policy is stateless, so there is nothing to reset. Keeping this
    function makes scenario runs interchangeable with the original stub.
    """


def price_cap(config: SimConfig) -> float:
    """Return the absolute P2P ask-price cap in EUR/kWh."""
    return round(config.grid_retail_price * PRICE_CAP_FACTOR, 4)


def _clip(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def get_policy(
    step: int,
    previous_metrics: Optional[StepMetrics],
    config: SimConfig,
) -> Policy:
    """Return the regulator policy for one simulation step.

    ``previous_metrics`` is always from step ``step - 1`` in the simulator.
    Violators are therefore banned for exactly the following P2P step.
    """
    mode = config.regulator_mode

    if mode == "none":
        return Policy(
            step=step,
            mode="none",
            p2p_bonus_eur_per_kwh=0.0,
            priority_rule="price",
            banned_prosumers=[],
            price_cap_eur_per_kwh=None,
            max_markup=None,
            note="baseline: price-only P2P trading",
        )

    if mode not in ("fixed", "adaptive"):
        raise ValueError(f"unknown regulator mode {mode!r}")

    banned = sorted(set(previous_metrics.violators)) if previous_metrics else []

    if mode == "fixed":
        bonus = FIXED_BONUS
        note = f"fixed P2P bonus {FIXED_BONUS:.4f} EUR/kWh"
    else:
        # At night (or any step with no simultaneous surplus and deficit), P2P
        # trading is physically impossible. Do not react to a zero P2P share in
        # that case because it would create artificial incentive wind-up.
        if previous_metrics is None or previous_metrics.tradable_kwh <= EPS:
            bonus = FIXED_BONUS
            note = "adaptive warm-up/no tradable energy: base bonus"
        else:
            observed = _clip(previous_metrics.p2p_potential_share, 0.0, 1.0)
            error = TARGET_P2P_SHARE - observed
            # Stateless proportional feedback. At the target the incentive is
            # exactly FIXED_BONUS; below target it rises, above target it falls.
            # Because it does not reconstruct the previous bonus from subsidy
            # spending, it also behaves correctly when previous P2P_kWh == 0.
            bonus = _clip(FIXED_BONUS + ADAPTIVE_GAIN * error, 0.0, MAX_BONUS)
            note = (
                f"adaptive target={TARGET_P2P_SHARE:.0%}, "
                f"previous={observed:.1%}, error={error:+.3f}"
            )

    return Policy(
        step=step,
        mode=mode,
        p2p_bonus_eur_per_kwh=round(bonus, 5),
        priority_rule="green_first",
        banned_prosumers=banned,
        price_cap_eur_per_kwh=price_cap(config),
        max_markup=MAX_MARKUP,
        note=note,
    )
