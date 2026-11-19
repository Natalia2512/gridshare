"""Member 3 - per-step KPIs for GridShare 100."""
from __future__ import annotations

from typing import Dict, Iterable, List

from .contract import (
    AGGREGATOR_ID,
    MARKET_LOCAL,
    MARKET_P2P,
    SIDE_SELL,
    MarketResult,
    Order,
    Policy,
    ProsumerState,
    StepMetrics,
)

EPS = 1e-9


def jain_index(values: Iterable[float]) -> float:
    """Jain fairness index in [0, 1]; 1 means equal values.

    Here it is applied to the average unit energy cost paid by buyers that
    traded in the current step.
    """
    vals = [float(v) for v in values if v >= 0]
    if not vals or sum(vals) <= EPS:
        return 1.0
    numerator = sum(vals) ** 2
    denominator = len(vals) * sum(v * v for v in vals)
    return max(0.0, min(1.0, numerator / denominator))


def evaluate(
    step: int,
    prosumers: List[ProsumerState],
    orders: List[Order],
    market: MarketResult,
    policy: Policy,
) -> StepMetrics:
    """Compute the Member-3 metrics after market clearing for one step."""
    transactions = market.transactions
    p2p = [tx for tx in transactions if tx.market_type == MARKET_P2P]
    local = [tx for tx in transactions if tx.market_type == MARKET_LOCAL]

    total_demand = sum(p.demand_kwh for p in prosumers)
    total_pv = sum(p.pv_kwh for p in prosumers)
    self_consumed = sum(p.self_consumed_kwh for p in prosumers)
    total_surplus = sum(p.surplus_kwh for p in prosumers)
    total_deficit = sum(p.deficit_kwh for p in prosumers)

    p2p_kwh = sum(tx.quantity_kwh for tx in p2p)
    local_buy_kwh = sum(
        tx.quantity_kwh for tx in local if tx.seller_id == AGGREGATOR_ID
    )
    local_sell_kwh = sum(
        tx.quantity_kwh for tx in local if tx.buyer_id == AGGREGATOR_ID
    )

    # Only simultaneous surplus and deficit can physically be matched P2P.
    tradable_kwh = min(total_surplus, total_deficit)
    p2p_of_tradable = (
        min(1.0, max(0.0, p2p_kwh / tradable_kwh))
        if tradable_kwh > EPS
        else 0.0
    )

    traded_kwh = p2p_kwh + local_buy_kwh + local_sell_kwh
    p2p_share = p2p_kwh / traded_kwh if traded_kwh > EPS else 0.0

    # Contract definition: share of community demand covered by community PV.
    # After self-balancing, the aggregator nets remaining local surplus against
    # remaining local deficit before importing/exporting externally. Therefore
    # local PV can serve demand through self-consumption, P2P, *or* the local
    # aggregator market. At community level this is min(total PV, total demand).
    renewable_share = (
        min(total_pv, total_demand) / total_demand
        if total_demand > EPS
        else 0.0
    )

    weighted_p2p_value = sum(
        tx.quantity_kwh * tx.price_eur_per_kwh for tx in p2p
    )
    avg_p2p_price = weighted_p2p_value / p2p_kwh if p2p_kwh > EPS else 0.0

    # P2P payments remain inside the community. External/community-level energy
    # cost is therefore what prosumers pay to the aggregator for LOCAL buys,
    # minus what the aggregator pays them for LOCAL sells.
    paid_to_aggregator = sum(
        tx.quantity_kwh * tx.price_eur_per_kwh
        for tx in local
        if tx.seller_id == AGGREGATOR_ID
    )
    received_from_aggregator = sum(
        tx.quantity_kwh * tx.price_eur_per_kwh
        for tx in local
        if tx.buyer_id == AGGREGATOR_ID
    )
    community_cost = paid_to_aggregator - received_from_aggregator

    regulator_bonus = p2p_kwh * policy.p2p_bonus_eur_per_kwh

    # Fairness of unit purchase price among buyers that actually bought energy.
    buyer_costs: Dict[str, List[float]] = {}
    for tx in transactions:
        if tx.buyer_id == AGGREGATOR_ID:
            continue
        total = buyer_costs.setdefault(tx.buyer_id, [0.0, 0.0])
        total[0] += tx.quantity_kwh * tx.price_eur_per_kwh
        total[1] += tx.quantity_kwh
    unit_costs = [cost / qty for cost, qty in buyer_costs.values() if qty > EPS]
    fairness = jain_index(unit_costs)

    # Anti-gouging violations are detected now and enforced by the next step's
    # regulator policy. Baseline policy has no caps, so it produces no bans.
    forecast_by_id = {p.prosumer_id: p.forecast_price for p in prosumers}
    violators = set()
    for order in orders:
        if order.side != SIDE_SELL:
            continue
        if (
            policy.price_cap_eur_per_kwh is not None
            and order.limit_price > policy.price_cap_eur_per_kwh + EPS
        ):
            violators.add(order.prosumer_id)
        if policy.max_markup is not None:
            forecast = forecast_by_id[order.prosumer_id]
            if order.limit_price > forecast * (1.0 + policy.max_markup) + EPS:
                violators.add(order.prosumer_id)

    return StepMetrics(
        step=step,
        total_demand_kwh=round(total_demand, 4),
        total_pv_kwh=round(total_pv, 4),
        self_consumed_kwh=round(self_consumed, 4),
        p2p_kwh=round(p2p_kwh, 4),
        local_buy_kwh=round(local_buy_kwh, 4),
        local_sell_kwh=round(local_sell_kwh, 4),
        grid_import_kwh=round(market.residual_import_kwh, 4),
        grid_export_kwh=round(market.residual_export_kwh, 4),
        renewable_share=round(renewable_share, 4),
        p2p_share=round(p2p_share, 4),
        tradable_kwh=round(tradable_kwh, 4),
        p2p_potential_share=round(p2p_of_tradable, 4),
        avg_p2p_price=round(avg_p2p_price, 4),
        community_cost_eur=round(community_cost, 4),
        regulator_bonus_eur=round(regulator_bonus, 4),
        fairness_jain=round(fairness, 4),
        n_p2p_trades=len(p2p),
        n_local_trades=len(local),
        n_banned=len(policy.banned_prosumers),
        violators=sorted(violators),
    )
