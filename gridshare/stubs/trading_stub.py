"""STUB for Member 2 - bilateral P2P negotiation + local market via aggregator.

Stage 2 (P2P), following the course hint (sorting instead of optimisation):
* banned prosumers are excluded from P2P (regulator rule);
* the regulator bonus is paid to P2P sellers, so a seller accepts
  effective_ask = limit_price - bonus;
* asks sorted cheapest first (green sellers first on ties if priority_rule ==
  "green_first"), bids sorted highest first; trade while bid >= effective ask,
  with partial fills; price = midpoint of bid and effective ask.

Stage 3 (local market): every remaining surplus/deficit is settled with the
aggregator (ID "AGGREGATOR"). The aggregator nets local buys and sells at the
mid price between grid retail and feed-in tariffs and imports/exports only the
net remainder from/to the external grid. It is budget-balanced.
"""
from __future__ import annotations

from typing import Dict, List

from ..contract import (AGGREGATOR_ID, MARKET_LOCAL, MARKET_P2P, SIDE_BUY, SIDE_SELL,
                        MarketResult, Order, Policy, ProsumerState, SimConfig, Transaction)

Q_EPS = 1e-6


def clear_markets(step: int, orders: List[Order], prosumers: List[ProsumerState],
                  policy: Policy, config: SimConfig) -> MarketResult:
    banned = set(policy.banned_prosumers)
    bonus = policy.p2p_bonus_eur_per_kwh
    asks = [[o, o.quantity_kwh, max(0.0, o.limit_price - bonus)]
            for o in orders if o.side == SIDE_SELL and o.prosumer_id not in banned]
    bids = [[o, o.quantity_kwh] for o in orders if o.side == SIDE_BUY and o.prosumer_id not in banned]

    if policy.priority_rule == "green_first":
        asks.sort(key=lambda a: (round(a[2], 6), 0 if a[0].behaviour == "green" else 1, a[0].prosumer_id))
    else:
        asks.sort(key=lambda a: (round(a[2], 6), a[0].prosumer_id))
    bids.sort(key=lambda b: (-b[0].limit_price, b[0].prosumer_id))

    txs: List[Transaction] = []
    bought: Dict[str, float] = {}
    sold: Dict[str, float] = {}
    i = j = 0
    while i < len(bids) and j < len(asks):
        bid, bid_left = bids[i]
        ask, ask_left, eff_ask = asks[j]
        if bid.limit_price + 1e-12 < eff_ask:
            break
        q = min(bid_left, ask_left)
        price = round((bid.limit_price + eff_ask) / 2.0, 4)
        txs.append(Transaction(f"T{step:03d}-P{len(txs) + 1:04d}", step, bid.prosumer_id,
                               ask.prosumer_id, round(q, 6), price, MARKET_P2P))
        bought[bid.prosumer_id] = bought.get(bid.prosumer_id, 0.0) + round(q, 6)
        sold[ask.prosumer_id] = sold.get(ask.prosumer_id, 0.0) + round(q, 6)
        bids[i][1] -= q
        asks[j][1] -= q
        if bids[i][1] <= Q_EPS:
            i += 1
        if asks[j][1] <= Q_EPS:
            j += 1

    # ---- Stage 3: local market through the aggregator -------------------- #
    local_buys = []   # (prosumer_id, qty)
    local_sells = []
    for p in prosumers:
        rest_def = round(p.deficit_kwh - bought.get(p.prosumer_id, 0.0), 6)
        rest_sur = round(p.surplus_kwh - sold.get(p.prosumer_id, 0.0), 6)
        if rest_def > Q_EPS:
            local_buys.append((p.prosumer_id, rest_def))
        if rest_sur > Q_EPS:
            local_sells.append((p.prosumer_id, rest_sur))
    B = sum(q for _, q in local_buys)
    S = sum(q for _, q in local_sells)
    mid = (config.grid_retail_price + config.grid_feed_in_price) / 2.0
    netted = min(B, S)
    buy_price = (netted * mid + max(B - S, 0.0) * config.grid_retail_price) / B if B > 0 else mid
    sell_price = (netted * mid + max(S - B, 0.0) * config.grid_feed_in_price) / S if S > 0 else mid
    k = 0
    for pid, q in local_buys:
        k += 1
        txs.append(Transaction(f"T{step:03d}-L{k:04d}", step, pid, AGGREGATOR_ID, q,
                               round(buy_price, 4), MARKET_LOCAL))
    for pid, q in local_sells:
        k += 1
        txs.append(Transaction(f"T{step:03d}-L{k:04d}", step, AGGREGATOR_ID, pid, q,
                               round(sell_price, 4), MARKET_LOCAL))
    return MarketResult(step=step, transactions=txs,
                        residual_import_kwh=round(max(B - S, 0.0), 6),
                        residual_export_kwh=round(max(S - B, 0.0), 6))
