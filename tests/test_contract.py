"""Interface contract tests: the example files must always respect the contract."""
import dataclasses

import pytest

from gridshare import contract as C
from gridshare.fixtures import (FIXTURE_STEP, load_market, load_metrics, load_orders, load_policy,
                                load_previous_metrics, load_prosumers)


def test_fixtures_respect_contract():
    prosumers, orders, policy = load_prosumers(), load_orders(), load_policy()
    C.validate_prosumers(prosumers, 100, FIXTURE_STEP)
    C.validate_orders(orders, prosumers, FIXTURE_STEP)
    C.validate_market(load_market(), orders, prosumers, policy, FIXTURE_STEP)
    assert load_metrics().step == FIXTURE_STEP
    assert load_previous_metrics().step == FIXTURE_STEP - 1


def test_fixture_market_has_both_market_types():
    types = {t.market_type for t in load_market().transactions}
    assert types == {C.MARKET_P2P, C.MARKET_LOCAL}


def test_prosumer_balance_violation_detected():
    ps = load_prosumers()
    ps[0] = dataclasses.replace(ps[0], surplus_kwh=ps[0].surplus_kwh + 1)
    with pytest.raises(C.ContractError):
        C.validate_prosumers(ps, 100, FIXTURE_STEP)


def test_wrong_number_of_prosumers_detected():
    with pytest.raises(C.ContractError):
        C.validate_prosumers(load_prosumers()[:99], 100, FIXTURE_STEP)


def test_order_exceeding_surplus_detected():
    ps, orders = load_prosumers(), load_orders()
    orders[0] = dataclasses.replace(orders[0], quantity_kwh=orders[0].quantity_kwh + 5)
    with pytest.raises(C.ContractError):
        C.validate_orders(orders, ps, FIXTURE_STEP)


def test_market_overselling_detected():
    ps, orders, policy, market = load_prosumers(), load_orders(), load_policy(), load_market()
    p2p = next(i for i, t in enumerate(market.transactions) if t.market_type == C.MARKET_P2P)
    t = market.transactions[p2p]
    market.transactions[p2p] = dataclasses.replace(t, quantity_kwh=t.quantity_kwh + 10)
    with pytest.raises(C.ContractError):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)


def test_unsettled_imbalance_detected():
    ps, orders, policy, market = load_prosumers(), load_orders(), load_policy(), load_market()
    loc = next(i for i, t in enumerate(market.transactions)
               if t.market_type == C.MARKET_LOCAL)
    del market.transactions[loc]
    with pytest.raises(C.ContractError):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)


def test_banned_prosumer_cannot_trade_p2p():
    ps, orders, market = load_prosumers(), load_orders(), load_market()
    seller = next(t.seller_id for t in market.transactions if t.market_type == C.MARKET_P2P)
    policy = dataclasses.replace(load_policy(), banned_prosumers=[seller])
    with pytest.raises(C.ContractError, match="banned"):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)


def test_nan_values_detected():
    ps = load_prosumers()
    bad = [dataclasses.replace(ps[0], forecast_price=float("nan"))] + ps[1:]
    with pytest.raises(C.ContractError):
        C.validate_prosumers(bad, 100, FIXTURE_STEP)
    market = load_market()
    t = market.transactions[0]
    market.transactions[0] = dataclasses.replace(t, quantity_kwh=float("nan"))
    with pytest.raises(C.ContractError):
        C.validate_market(market, load_orders(), ps, load_policy(), FIXTURE_STEP)


def test_p2p_price_outside_bid_ask_detected():
    ps, orders, policy, market = load_prosumers(), load_orders(), load_policy(), load_market()
    i = next(i for i, t in enumerate(market.transactions) if t.market_type == C.MARKET_P2P)
    market.transactions[i] = dataclasses.replace(market.transactions[i], price_eur_per_kwh=5.0)
    with pytest.raises(C.ContractError, match="price"):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)


def test_unknown_counterparty_detected():
    ps, orders, policy, market = load_prosumers(), load_orders(), load_policy(), load_market()
    market.transactions.append(C.Transaction("GHOST-1", FIXTURE_STEP, "GHOST", C.AGGREGATOR_ID,
                                             10.0, 0.3, C.MARKET_LOCAL))
    market.residual_import_kwh += 10.0
    with pytest.raises(C.ContractError, match="unknown"):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)


@pytest.mark.parametrize("change", [
    {"step": 3}, {"p2p_bonus_eur_per_kwh": -3.0}, {"priority_rule": "whatever"},
    {"mode": "chaos"}, {"max_markup": float("nan")},
])
def test_bad_policy_detected(change):
    with pytest.raises(C.ContractError):
        C.validate_policy(dataclasses.replace(load_policy(), **change), FIXTURE_STEP)


def test_bad_metrics_type_detected():
    with pytest.raises(C.ContractError):
        C.validate_metrics({"step": 1}, 1)


def test_unknown_banned_and_nan_metrics_detected():
    ps, orders, market = load_prosumers(), load_orders(), load_market()
    policy = dataclasses.replace(load_policy(), banned_prosumers=["NOBODY"])
    with pytest.raises(C.ContractError, match="unknown"):
        C.validate_market(market, orders, ps, policy, FIXTURE_STEP)
    with pytest.raises(C.ContractError, match="finite"):
        C.validate_metrics(C.StepMetrics(step=1, tradable_kwh=float("nan")), 1)
