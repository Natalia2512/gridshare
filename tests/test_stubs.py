"""Tests of the stubs for Members 1-3 (they double as acceptance tests for the
real modules: the same checks must pass when the real code replaces them)."""
from gridshare import contract as C
from gridshare.fixtures import FIXTURE_STEP, load_orders, load_policy, load_prosumers
from gridshare.simulation import config_for, load_modules

F, MODS, _ = load_modules(use_stubs=True)
CFG = config_for("adaptive")


def test_prosumers_100_valid_records_every_step():
    for step in range(24):
        ps = F["prosumer"](step, 42, None, CFG)
        C.validate_prosumers(ps, 100, step)
    night = F["prosumer"](2, 42, None, CFG)
    assert sum(p.pv_kwh for p in night) == 0


def test_pv_shortage_scales_pv():
    full = sum(p.pv_kwh for p in F["prosumer"](12, 42, None, config_for("adaptive")))
    low = sum(p.pv_kwh for p in F["prosumer"](12, 42, None, config_for("pv_shortage")))
    assert 0.2 * full < low < 0.4 * full


def test_decisions_respect_capacity_and_behaviour():
    ps = load_prosumers()
    orders = F["decision"](FIXTURE_STEP, ps, CFG)
    C.validate_orders(orders, ps, FIXTURE_STEP)
    by_type = {}
    for o in orders:
        if o.side == C.SIDE_SELL:
            by_type.setdefault(o.behaviour, []).append(o.limit_price)
    avg = {k: sum(v) / len(v) for k, v in by_type.items()}
    assert avg["aggressive"] > avg["conservative"] > avg["green"]


def test_trading_on_fixture_inputs():
    ps, orders, policy = load_prosumers(), load_orders(), load_policy()
    market = F["trading"](FIXTURE_STEP, orders, ps, policy, CFG)
    C.validate_market(market, orders, ps, policy, FIXTURE_STEP)
    assert any(t.market_type == C.MARKET_P2P for t in market.transactions)


def test_partial_fill_and_price_between_bid_and_ask():
    ps = load_prosumers()
    seller = next(p for p in ps if p.surplus_kwh > 1)
    buyer = next(p for p in ps if p.deficit_kwh > 0.1)
    orders = [C.Order("s", FIXTURE_STEP, seller.prosumer_id, C.SIDE_SELL, seller.surplus_kwh, 0.10),
              C.Order("b", FIXTURE_STEP, buyer.prosumer_id, C.SIDE_BUY, buyer.deficit_kwh, 0.20)]
    sub = [seller, buyer]
    m = F["trading"](FIXTURE_STEP, orders, sub, C.Policy(FIXTURE_STEP), CFG)
    p2p = [t for t in m.transactions if t.market_type == C.MARKET_P2P]
    assert len(p2p) == 1 and abs(p2p[0].quantity_kwh - buyer.deficit_kwh) < 1e-6
    assert 0.10 <= p2p[0].price_eur_per_kwh <= 0.20
    C.validate_market(m, orders, sub, C.Policy(FIXTURE_STEP), FIXTURE_STEP)


def test_regulator_ban_and_bonus_change_trading():
    ps, orders = load_prosumers(), load_orders()
    neutral = C.Policy(FIXTURE_STEP)
    m0 = F["trading"](FIXTURE_STEP, orders, ps, neutral, CFG)
    sellers = sorted({t.seller_id for t in m0.transactions if t.market_type == C.MARKET_P2P})
    banned = C.Policy(FIXTURE_STEP, banned_prosumers=sellers[:3])
    m1 = F["trading"](FIXTURE_STEP, orders, ps, banned, CFG)
    assert not {t.seller_id for t in m1.transactions if t.market_type == C.MARKET_P2P} & set(sellers[:3])
    bonus = C.Policy(FIXTURE_STEP, p2p_bonus_eur_per_kwh=0.08)
    m2 = F["trading"](FIXTURE_STEP, orders, ps, bonus, CFG)
    p2p = lambda m: sum(t.quantity_kwh for t in m.transactions if t.market_type == C.MARKET_P2P)
    assert p2p(m2) >= p2p(m0)


def test_regulator_deterministic():
    prev = C.StepMetrics(step=11, p2p_share=0.3, p2p_potential_share=0.5, violators=["P003"])
    MODS["regulator"].reset()
    a = F["regulator"](12, prev, CFG)
    MODS["regulator"].reset()
    b = F["regulator"](12, prev, CFG)
    assert a == b and a.banned_prosumers == ["P003"]
    assert F["regulator"](12, prev, config_for("baseline")).p2p_bonus_eur_per_kwh == 0
