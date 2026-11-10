"""Shared interface contract for GridShare 100.

FROZEN ON DAY 1. Every module (Members 1-4) exchanges data ONLY through the
types and function signatures defined here. Changing anything in this file
requires a versioned pull request agreed by the whole team (bump
CONTRACT_VERSION).

Units: 1 time step = 1 hour, energy in kWh, prices in EUR/kWh.

Module ownership and the function each module must expose
--------------------------------------------------------
Member 1  gridshare/prosumer.py   simulate_step(step, seed, prev_state, config) -> list[ProsumerState]
Member 1  gridshare/decision.py   decide_orders(step, prosumers, config) -> list[Order]
Member 2  gridshare/trading.py    clear_markets(step, orders, prosumers, policy, config) -> MarketResult
Member 3  gridshare/regulator.py  get_policy(step, previous_metrics, config) -> Policy
Member 3  gridshare/metrics.py    evaluate(step, prosumers, orders, market, policy) -> StepMetrics
Member 3  gridshare/charts.py     make_charts(step_metrics_by_scenario, out_dir) -> list[str]
Member 4  gridshare/blockchain.py Blockchain.append_transactions(step, transactions) -> BlockResult
Member 4  gridshare/simulation.py run_simulation(config) -> SimulationResult
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

CONTRACT_VERSION = "1.1"   # 1.1: tradable_kwh, max_markup, stricter validation.
# Always build dataclasses with KEYWORD arguments, e.g. StepMetrics(step=3, p2p_kwh=1.2).

AGGREGATOR_ID = "AGGREGATOR"
MARKET_P2P = "P2P"
MARKET_LOCAL = "LOCAL"
MARKET_TYPES = (MARKET_P2P, MARKET_LOCAL)
SIDE_BUY = "BUY"
SIDE_SELL = "SELL"
BEHAVIOUR_TYPES = ("conservative", "aggressive", "green")
EPS = 1e-9


# --------------------------------------------------------------------------- #
# Simulation configuration (shared by everybody)
# --------------------------------------------------------------------------- #
@dataclass
class SimConfig:
    n_prosumers: int = 100
    n_steps: int = 24
    seed: int = 42
    scenario: str = "adaptive"          # baseline | fixed | adaptive | pv_shortage
    regulator_mode: str = "adaptive"    # none | fixed | adaptive
    pv_scale: float = 1.0               # < 1.0 for the PV-shortage stress test
    n_validators: int = 10
    faulty_validators: int = 0          # validators that refuse to sign (robustness demo)
    grid_retail_price: float = 0.30     # EUR/kWh paid when the aggregator imports from the grid
    grid_feed_in_price: float = 0.06    # EUR/kWh received when the aggregator exports to the grid
    use_stubs: bool = False             # force stub modules even if real ones exist


# --------------------------------------------------------------------------- #
# Member 1 -> everybody
# --------------------------------------------------------------------------- #
@dataclass
class ProsumerState:
    prosumer_id: str
    step: int
    behaviour: str              # one of BEHAVIOUR_TYPES
    pv_kwh: float               # actual PV generation in this step (>= 0)
    demand_kwh: float           # actual demand in this step (>= 0)
    pv_forecast_kwh: float      # forecast made before the step
    forecast_price: float       # EUR/kWh, forecast local price for this step
    self_consumed_kwh: float    # min(pv, demand)
    surplus_kwh: float          # max(pv - demand, 0)
    deficit_kwh: float          # max(demand - pv, 0)

    @property
    def net_kwh(self) -> float:
        return self.surplus_kwh - self.deficit_kwh


@dataclass
class Order:
    """A bid (BUY) or ask (SELL) created by Member 1's decision model."""
    order_id: str
    step: int
    prosumer_id: str
    side: str                   # SIDE_BUY | SIDE_SELL
    quantity_kwh: float         # > 0
    limit_price: float          # EUR/kWh: max price for BUY, min price for SELL
    behaviour: str = "conservative"


# --------------------------------------------------------------------------- #
# Member 3 -> Member 2 (policy) and Member 3 -> everybody (metrics)
# --------------------------------------------------------------------------- #
@dataclass
class Policy:
    step: int
    mode: str = "none"                       # none | fixed | adaptive
    p2p_bonus_eur_per_kwh: float = 0.0       # paid by the regulator to P2P sellers
    priority_rule: str = "price"             # price | green_first
    banned_prosumers: List[str] = field(default_factory=list)  # excluded from P2P this step
    price_cap_eur_per_kwh: Optional[float] = None  # absolute cap: asks above it are a violation
    max_markup: Optional[float] = None       # relative cap: ask > forecast_price * (1 + max_markup) is a violation
    note: str = ""


@dataclass
class StepMetrics:
    step: int
    total_demand_kwh: float = 0.0
    total_pv_kwh: float = 0.0
    self_consumed_kwh: float = 0.0
    p2p_kwh: float = 0.0
    local_buy_kwh: float = 0.0
    local_sell_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    renewable_share: float = 0.0             # share of demand covered by community PV
    p2p_share: float = 0.0                   # P2P kWh / traded kWh
    tradable_kwh: float = 0.0                # min(total surplus, total deficit): energy that COULD be traded P2P
    p2p_potential_share: float = 0.0         # P2P kWh / tradable_kwh: how much of
                                             # the energy that COULD be traded locally was traded P2P
    avg_p2p_price: float = 0.0
    community_cost_eur: float = 0.0          # net payments to the aggregator (energy from/to outside the community)
    regulator_bonus_eur: float = 0.0         # paid by the regulator to P2P sellers (prosumers pay cost - bonus)
    fairness_jain: float = 1.0               # Jain index of per-buyer unit cost
    n_p2p_trades: int = 0
    n_local_trades: int = 0
    n_banned: int = 0
    violators: List[str] = field(default_factory=list)
    block_hash: str = ""
    block_validators: int = 0


# --------------------------------------------------------------------------- #
# Member 2 -> Member 3 and Member 4
# --------------------------------------------------------------------------- #
@dataclass
class Transaction:
    transaction_id: str
    step: int
    buyer_id: str
    seller_id: str
    quantity_kwh: float
    price_eur_per_kwh: float
    market_type: str            # MARKET_P2P | MARKET_LOCAL

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MarketResult:
    step: int
    transactions: List[Transaction]
    residual_import_kwh: float     # bought by the aggregator from the external grid
    residual_export_kwh: float     # sold by the aggregator to the external grid


# --------------------------------------------------------------------------- #
# Member 4 outputs
# --------------------------------------------------------------------------- #
@dataclass
class BlockResult:
    step: int
    block_index: int
    block_hash: str
    proposer_id: str
    validator_ids: List[str]       # validators whose signatures are in the block
    n_transactions: int
    valid: bool


@dataclass
class SimulationResult:
    config: SimConfig
    metrics: List[StepMetrics]
    blocks: List[BlockResult]
    chain_valid: bool
    chain_errors: List[str]
    all_trades_on_chain: bool
    module_sources: Dict[str, str]  # which implementation was used (real / stub)
    energy_balance_ok: bool
    transactions: List[Transaction] = field(default_factory=list)
    ledger: object = None           # the Blockchain instance (Member 4)


# --------------------------------------------------------------------------- #
# Validation helpers (used by tests, by simulation.py and by CI)
# --------------------------------------------------------------------------- #
class ContractError(ValueError):
    pass


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _close(a: float, b: float, tol: float) -> bool:
    """NaN-safe |a - b| <= tol."""
    return abs(a - b) <= tol


def validate_prosumers(prosumers: List[ProsumerState], n_expected: int, step: int) -> None:
    if len(prosumers) != n_expected:
        raise ContractError(f"step {step}: expected {n_expected} prosumers, got {len(prosumers)}")
    ids = set()
    for p in prosumers:
        if p.prosumer_id in ids:
            raise ContractError(f"duplicate prosumer_id {p.prosumer_id}")
        ids.add(p.prosumer_id)
        if p.step != step:
            raise ContractError(f"{p.prosumer_id}: step {p.step} != {step}")
        if p.behaviour not in BEHAVIOUR_TYPES:
            raise ContractError(f"{p.prosumer_id}: unknown behaviour {p.behaviour}")
        for name in ("pv_kwh", "demand_kwh", "surplus_kwh", "deficit_kwh", "self_consumed_kwh",
                     "pv_forecast_kwh", "forecast_price"):
            v = getattr(p, name)
            if not _finite(v):
                raise ContractError(f"{p.prosumer_id}: {name} is not a finite number ({v!r})")
            if v < -EPS:
                raise ContractError(f"{p.prosumer_id}: negative {name}")
        if p.surplus_kwh > EPS and p.deficit_kwh > EPS:
            raise ContractError(f"{p.prosumer_id}: both surplus and deficit > 0")
        if not _close(p.self_consumed_kwh + p.surplus_kwh, p.pv_kwh, 1e-6):
            raise ContractError(f"{p.prosumer_id}: PV balance broken")
        if not _close(p.self_consumed_kwh + p.deficit_kwh, p.demand_kwh, 1e-6):
            raise ContractError(f"{p.prosumer_id}: demand balance broken")


def validate_orders(orders: List[Order], prosumers: List[ProsumerState], step: int) -> None:
    by_id = {p.prosumer_id: p for p in prosumers}
    seen = set()
    for o in orders:
        if o.order_id in seen:
            raise ContractError(f"duplicate order_id {o.order_id}")
        seen.add(o.order_id)
        if o.step != step:
            raise ContractError(f"order {o.order_id}: wrong step")
        if o.prosumer_id not in by_id:
            raise ContractError(f"order {o.order_id}: unknown prosumer {o.prosumer_id}")
        if o.side not in (SIDE_BUY, SIDE_SELL):
            raise ContractError(f"order {o.order_id}: bad side {o.side}")
        if not _finite(o.quantity_kwh, o.limit_price):
            raise ContractError(f"order {o.order_id}: quantity/price must be finite numbers")
        if o.quantity_kwh <= 0:
            raise ContractError(f"order {o.order_id}: quantity must be > 0")
        if o.limit_price < 0:
            raise ContractError(f"order {o.order_id}: negative price")
        p = by_id[o.prosumer_id]
        cap = p.surplus_kwh if o.side == SIDE_SELL else p.deficit_kwh
        if o.quantity_kwh > cap + 1e-6:
            raise ContractError(f"order {o.order_id}: quantity exceeds {o.side} capacity of {o.prosumer_id}")


def validate_transaction(tx: Transaction) -> List[str]:
    """Return a list of problems (empty list = valid). Used by blockchain validators."""
    errs = []
    if not tx.transaction_id or not isinstance(tx.transaction_id, str):
        errs.append("missing transaction_id")
    if not isinstance(tx.buyer_id, str) or not isinstance(tx.seller_id, str) or not isinstance(tx.step, int):
        errs.append(f"{tx.transaction_id}: buyer_id/seller_id must be strings and step an integer")
    if not _finite(tx.quantity_kwh, tx.price_eur_per_kwh):
        errs.append(f"{tx.transaction_id}: quantity/price must be finite numbers")
        return errs
    if tx.quantity_kwh <= 0:
        errs.append(f"{tx.transaction_id}: quantity must be > 0")
    if tx.price_eur_per_kwh < 0:
        errs.append(f"{tx.transaction_id}: negative price")
    if tx.buyer_id == tx.seller_id:
        errs.append(f"{tx.transaction_id}: buyer == seller")
    if tx.market_type not in MARKET_TYPES:
        errs.append(f"{tx.transaction_id}: bad market_type {tx.market_type}")
    if tx.market_type == MARKET_LOCAL and AGGREGATOR_ID not in (tx.buyer_id, tx.seller_id):
        errs.append(f"{tx.transaction_id}: LOCAL trade without aggregator counterparty")
    if tx.market_type == MARKET_P2P and AGGREGATOR_ID in (tx.buyer_id, tx.seller_id):
        errs.append(f"{tx.transaction_id}: P2P trade cannot involve the aggregator")
    return errs


def validate_market(market: MarketResult, orders: List[Order], prosumers: List[ProsumerState],
                    policy: Policy, step: int) -> None:
    """Checks Member 2's output.

    * P2P quantities never exceed what was offered / requested in the orders.
    * P2P + LOCAL quantities exactly cover each prosumer's surplus and deficit
      (every imbalance is settled; anything not traded P2P goes to the aggregator).
    * Banned prosumers never trade P2P.
    """
    p2p_sell_cap: Dict[str, float] = {}
    p2p_buy_cap: Dict[str, float] = {}
    min_ask: Dict[str, float] = {}
    max_bid: Dict[str, float] = {}
    for o in orders:
        d = p2p_sell_cap if o.side == SIDE_SELL else p2p_buy_cap
        d[o.prosumer_id] = d.get(o.prosumer_id, 0.0) + o.quantity_kwh
        if o.side == SIDE_SELL:
            min_ask[o.prosumer_id] = min(min_ask.get(o.prosumer_id, o.limit_price), o.limit_price)
        else:
            max_bid[o.prosumer_id] = max(max_bid.get(o.prosumer_id, o.limit_price), o.limit_price)
    known = {p.prosumer_id for p in prosumers}
    validate_policy(policy, step)
    unknown_banned = set(policy.banned_prosumers) - known
    if unknown_banned:
        raise ContractError(f"policy bans unknown prosumers {sorted(unknown_banned)[:5]}")
    p2p_sold: Dict[str, float] = {}
    p2p_bought: Dict[str, float] = {}
    sold: Dict[str, float] = {}
    bought: Dict[str, float] = {}
    ids = set()
    banned = set(policy.banned_prosumers)
    for tx in market.transactions:
        errs = validate_transaction(tx)
        if errs:
            raise ContractError("; ".join(errs))
        if tx.step != step:
            raise ContractError(f"{tx.transaction_id}: wrong step")
        if tx.transaction_id in ids:
            raise ContractError(f"duplicate transaction_id {tx.transaction_id}")
        ids.add(tx.transaction_id)
        for who in (tx.buyer_id, tx.seller_id):
            if who != AGGREGATOR_ID and who not in known:
                raise ContractError(f"{tx.transaction_id}: unknown counterparty {who!r}")
        if tx.market_type == MARKET_P2P:
            if tx.buyer_id in banned or tx.seller_id in banned:
                raise ContractError(f"{tx.transaction_id}: banned prosumer traded P2P")
            if tx.seller_id not in min_ask or tx.buyer_id not in max_bid:
                raise ContractError(f"{tx.transaction_id}: P2P trade without a matching ask and bid")
            lo = min_ask[tx.seller_id] - policy.p2p_bonus_eur_per_kwh
            hi = max_bid[tx.buyer_id]
            if not (lo - 1e-4 <= tx.price_eur_per_kwh <= hi + 1e-4):
                raise ContractError(f"{tx.transaction_id}: P2P price {tx.price_eur_per_kwh} outside "
                                    f"[ask - bonus = {lo:.4f}, bid = {hi:.4f}]")
            p2p_sold[tx.seller_id] = p2p_sold.get(tx.seller_id, 0.0) + tx.quantity_kwh
            p2p_bought[tx.buyer_id] = p2p_bought.get(tx.buyer_id, 0.0) + tx.quantity_kwh
        if tx.seller_id != AGGREGATOR_ID:
            sold[tx.seller_id] = sold.get(tx.seller_id, 0.0) + tx.quantity_kwh
        if tx.buyer_id != AGGREGATOR_ID:
            bought[tx.buyer_id] = bought.get(tx.buyer_id, 0.0) + tx.quantity_kwh
    for pid, q in p2p_sold.items():
        if q > p2p_sell_cap.get(pid, 0.0) + 1e-6:
            raise ContractError(f"{pid} sold {q:.4f} kWh P2P > offered {p2p_sell_cap.get(pid, 0.0):.4f}")
    for pid, q in p2p_bought.items():
        if q > p2p_buy_cap.get(pid, 0.0) + 1e-6:
            raise ContractError(f"{pid} bought {q:.4f} kWh P2P > requested {p2p_buy_cap.get(pid, 0.0):.4f}")
    for p in prosumers:
        if not _close(sold.get(p.prosumer_id, 0.0), p.surplus_kwh, 1e-4):
            raise ContractError(f"{p.prosumer_id}: surplus {p.surplus_kwh:.4f} not fully settled "
                                f"(sold {sold.get(p.prosumer_id, 0.0):.4f})")
        if not _close(bought.get(p.prosumer_id, 0.0), p.deficit_kwh, 1e-4):
            raise ContractError(f"{p.prosumer_id}: deficit {p.deficit_kwh:.4f} not fully settled "
                                f"(bought {bought.get(p.prosumer_id, 0.0):.4f})")
    if not _finite(market.residual_import_kwh, market.residual_export_kwh):
        raise ContractError("residual import/export must be finite numbers")
    if market.residual_import_kwh < -EPS or market.residual_export_kwh < -EPS:
        raise ContractError("negative residual import/export")
    local_buy = sum(t.quantity_kwh for t in market.transactions
                    if t.market_type == MARKET_LOCAL and t.seller_id == AGGREGATOR_ID)
    local_sell = sum(t.quantity_kwh for t in market.transactions
                     if t.market_type == MARKET_LOCAL and t.buyer_id == AGGREGATOR_ID)
    if not _close(market.residual_import_kwh - market.residual_export_kwh, local_buy - local_sell, 1e-4):
        raise ContractError("aggregator balance broken: grid import - export != local buys - local sells")


PRIORITY_RULES = ("price", "green_first")
REGULATOR_MODES = ("none", "fixed", "adaptive")


def validate_policy(policy: Policy, step: int) -> None:
    """Checks Member 3's policy before it is used by Member 2."""
    if not isinstance(policy, Policy):
        raise ContractError(f"get_policy() must return a Policy, got {type(policy).__name__}")
    if policy.step != step:
        raise ContractError(f"policy step {policy.step} != {step}")
    if policy.mode not in REGULATOR_MODES:
        raise ContractError(f"policy mode {policy.mode!r} not in {REGULATOR_MODES}")
    if not _finite(policy.p2p_bonus_eur_per_kwh) or policy.p2p_bonus_eur_per_kwh < 0:
        raise ContractError("p2p_bonus_eur_per_kwh must be a finite number >= 0")
    if policy.priority_rule not in PRIORITY_RULES:
        raise ContractError(f"priority_rule {policy.priority_rule!r} not in {PRIORITY_RULES}")
    for name in ("price_cap_eur_per_kwh", "max_markup"):
        v = getattr(policy, name)
        if v is not None and (not _finite(v) or v < 0):
            raise ContractError(f"{name} must be None or a finite number >= 0")


def validate_metrics(metrics: StepMetrics, step: int) -> None:
    """Checks Member 3's metrics before they are fed back to the regulator."""
    if not isinstance(metrics, StepMetrics):
        raise ContractError(f"evaluate() must return StepMetrics, got {type(metrics).__name__}")
    if metrics.step != step:
        raise ContractError(f"metrics step {metrics.step} != {step}")
    for name, v in asdict(metrics).items():
        if isinstance(v, float) and not math.isfinite(v):
            raise ContractError(f"metrics field {name} is not a finite number ({v!r})")
