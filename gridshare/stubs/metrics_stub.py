"""STUB for Member 3 - per-step evaluation metrics."""
from __future__ import annotations

from typing import Dict, List

from ..contract import (AGGREGATOR_ID, MARKET_LOCAL, MARKET_P2P, SIDE_SELL, MarketResult,
                        Order, Policy, ProsumerState, StepMetrics)


def jain(values: List[float]) -> float:
    vals = [v for v in values if v >= 0]
    if not vals or sum(vals) == 0:
        return 1.0
    return (sum(vals) ** 2) / (len(vals) * sum(v * v for v in vals))


def evaluate(step: int, prosumers: List[ProsumerState], orders: List[Order],
             market: MarketResult, policy: Policy) -> StepMetrics:
    txs = market.transactions
    p2p = [t for t in txs if t.market_type == MARKET_P2P]
    local = [t for t in txs if t.market_type == MARKET_LOCAL]
    demand = sum(p.demand_kwh for p in prosumers)
    pv = sum(p.pv_kwh for p in prosumers)
    self_c = sum(p.self_consumed_kwh for p in prosumers)
    p2p_kwh = sum(t.quantity_kwh for t in p2p)
    local_buy = sum(t.quantity_kwh for t in local if t.seller_id == AGGREGATOR_ID)
    local_sell = sum(t.quantity_kwh for t in local if t.buyer_id == AGGREGATOR_ID)
    traded = p2p_kwh + local_buy + local_sell
    bonus_eur = p2p_kwh * policy.p2p_bonus_eur_per_kwh

    # what the community pays outside: local-market purchases minus local-market sales
    # (P2P payments stay inside the community). The regulator bonus is reported separately.
    paid_local = sum(t.quantity_kwh * t.price_eur_per_kwh for t in local if t.seller_id == AGGREGATOR_ID)
    recv_local = sum(t.quantity_kwh * t.price_eur_per_kwh for t in local if t.buyer_id == AGGREGATOR_ID)
    community_cost = paid_local - recv_local          # energy bought from / sold to outside the community

    unit_cost: Dict[str, List[float]] = {}
    for t in txs:
        if t.buyer_id != AGGREGATOR_ID:
            c = unit_cost.setdefault(t.buyer_id, [0.0, 0.0])
            c[0] += t.quantity_kwh * t.price_eur_per_kwh
            c[1] += t.quantity_kwh
    fairness = jain([c[0] / c[1] for c in unit_cost.values() if c[1] > 0])

    fc = {p.prosumer_id: p.forecast_price for p in prosumers}
    violators = set()
    for o in orders:
        if o.side != SIDE_SELL:
            continue
        if policy.price_cap_eur_per_kwh is not None and o.limit_price > policy.price_cap_eur_per_kwh:
            violators.add(o.prosumer_id)
        if policy.max_markup is not None and o.limit_price > fc[o.prosumer_id] * (1 + policy.max_markup):
            violators.add(o.prosumer_id)
    violators = sorted(violators)
    potential = min(sum(p.surplus_kwh for p in prosumers), sum(p.deficit_kwh for p in prosumers))

    return StepMetrics(
        step=step,
        total_demand_kwh=round(demand, 4), total_pv_kwh=round(pv, 4),
        self_consumed_kwh=round(self_c, 4), p2p_kwh=round(p2p_kwh, 4),
        local_buy_kwh=round(local_buy, 4), local_sell_kwh=round(local_sell, 4),
        grid_import_kwh=round(market.residual_import_kwh, 4),
        grid_export_kwh=round(market.residual_export_kwh, 4),
        renewable_share=round(min(pv, demand) / demand, 4) if demand > 0 else 0.0,
        p2p_share=round(p2p_kwh / traded, 4) if traded > 0 else 0.0,
        tradable_kwh=round(potential, 4),
        p2p_potential_share=round(p2p_kwh / potential, 4) if potential > 1e-9 else 0.0,
        avg_p2p_price=round(sum(t.quantity_kwh * t.price_eur_per_kwh for t in p2p) / p2p_kwh, 4) if p2p_kwh > 0 else 0.0,
        community_cost_eur=round(community_cost, 4),
        regulator_bonus_eur=round(bonus_eur, 4),
        fairness_jain=round(fairness, 4),
        n_p2p_trades=len(p2p), n_local_trades=len(local),
        n_banned=len(policy.banned_prosumers), violators=violators,
    )
