"""Focused tests for Member 3's regulator and metrics modules."""
from gridshare import contract as C
from gridshare import metrics as M
from gridshare import regulator as R
from pathlib import Path


def test_baseline_policy_is_neutral():
    cfg = C.SimConfig(regulator_mode="none")
    policy = R.get_policy(3, None, cfg)
    C.validate_policy(policy, 3)
    assert policy.mode == "none"
    assert policy.p2p_bonus_eur_per_kwh == 0.0
    assert policy.priority_rule == "price"
    assert policy.banned_prosumers == []
    assert policy.price_cap_eur_per_kwh is None
    assert policy.max_markup is None


def test_fixed_policy_bans_previous_violators():
    cfg = C.SimConfig(regulator_mode="fixed")
    prev = C.StepMetrics(step=4, violators=["P007", "P003", "P007"])
    policy = R.get_policy(5, prev, cfg)
    C.validate_policy(policy, 5)
    assert policy.p2p_bonus_eur_per_kwh == R.FIXED_BONUS
    assert policy.banned_prosumers == ["P003", "P007"]
    assert policy.priority_rule == "green_first"


def test_adaptive_bonus_rises_after_low_utilisation_and_falls_after_high_utilisation():
    cfg = C.SimConfig(regulator_mode="adaptive")

    low = C.StepMetrics(
        step=10,
        p2p_kwh=10.0,
        tradable_kwh=20.0,
        p2p_potential_share=0.50,
        regulator_bonus_eur=10.0 * R.FIXED_BONUS,
    )
    after_low = R.get_policy(11, low, cfg)
    assert after_low.p2p_bonus_eur_per_kwh > R.FIXED_BONUS

    high = C.StepMetrics(
        step=11,
        p2p_kwh=10.0,
        tradable_kwh=10.0,
        p2p_potential_share=1.0,
        regulator_bonus_eur=10.0 * 0.03,
    )
    after_high = R.get_policy(12, high, cfg)
    assert after_high.p2p_bonus_eur_per_kwh < 0.03


def test_adaptive_policy_is_deterministic_for_same_input():
    cfg = C.SimConfig(regulator_mode="adaptive")
    prev = C.StepMetrics(
        step=8,
        p2p_kwh=5.0,
        tradable_kwh=10.0,
        p2p_potential_share=0.5,
        regulator_bonus_eur=0.075,
        violators=["P009"],
    )
    assert R.get_policy(9, prev, cfg) == R.get_policy(9, prev, cfg)


def test_metrics_measure_p2p_utilisation_renewables_cost_and_bonus():
    seller = C.ProsumerState(
        prosumer_id="P001",
        step=0,
        behaviour="green",
        pv_kwh=3.0,
        demand_kwh=1.0,
        pv_forecast_kwh=3.0,
        forecast_price=0.10,
        self_consumed_kwh=1.0,
        surplus_kwh=2.0,
        deficit_kwh=0.0,
    )
    buyer = C.ProsumerState(
        prosumer_id="P002",
        step=0,
        behaviour="conservative",
        pv_kwh=0.0,
        demand_kwh=3.0,
        pv_forecast_kwh=0.0,
        forecast_price=0.20,
        self_consumed_kwh=0.0,
        surplus_kwh=0.0,
        deficit_kwh=3.0,
    )
    orders = [
        C.Order("S", 0, "P001", C.SIDE_SELL, 2.0, 0.10, "green"),
        C.Order("B", 0, "P002", C.SIDE_BUY, 3.0, 0.20, "conservative"),
    ]
    market = C.MarketResult(
        step=0,
        transactions=[
            C.Transaction("T-P2P", 0, "P002", "P001", 2.0, 0.15, C.MARKET_P2P),
            C.Transaction("T-LOCAL", 0, "P002", C.AGGREGATOR_ID, 1.0, 0.30, C.MARKET_LOCAL),
        ],
        residual_import_kwh=1.0,
        residual_export_kwh=0.0,
    )
    policy = C.Policy(
        step=0,
        mode="fixed",
        p2p_bonus_eur_per_kwh=0.01,
        priority_rule="green_first",
        price_cap_eur_per_kwh=0.27,
        max_markup=0.20,
    )

    metrics = M.evaluate(0, [seller, buyer], orders, market, policy)
    C.validate_metrics(metrics, 0)

    assert metrics.p2p_kwh == 2.0
    assert metrics.tradable_kwh == 2.0
    assert metrics.p2p_potential_share == 1.0
    assert metrics.renewable_share == 0.75
    assert metrics.community_cost_eur == 0.30
    assert metrics.regulator_bonus_eur == 0.02
    assert metrics.fairness_jain == 1.0


def test_metrics_flags_anti_gouging_seller_for_next_step():
    seller = C.ProsumerState(
        prosumer_id="P001", step=0, behaviour="aggressive",
        pv_kwh=2.0, demand_kwh=0.0, pv_forecast_kwh=2.0,
        forecast_price=0.10, self_consumed_kwh=0.0,
        surplus_kwh=2.0, deficit_kwh=0.0,
    )
    order = C.Order("S", 0, "P001", C.SIDE_SELL, 2.0, 0.13, "aggressive")
    market = C.MarketResult(
        step=0,
        transactions=[
            C.Transaction("L", 0, C.AGGREGATOR_ID, "P001", 2.0, 0.06, C.MARKET_LOCAL)
        ],
        residual_import_kwh=0.0,
        residual_export_kwh=2.0,
    )
    policy = C.Policy(
        step=0, mode="fixed", priority_rule="green_first",
        price_cap_eur_per_kwh=0.27, max_markup=0.20,
    )
    metrics = M.evaluate(0, [seller], [order], market, policy)
    assert metrics.violators == ["P001"]



def test_adaptive_zero_p2p_with_tradable_energy_responds_strongly_and_deterministically():
    cfg = C.SimConfig(regulator_mode="adaptive")
    prev = C.StepMetrics(
        step=5,
        p2p_kwh=0.0,
        tradable_kwh=20.0,
        p2p_potential_share=0.0,
        regulator_bonus_eur=0.0,
    )
    a = R.get_policy(6, prev, cfg)
    b = R.get_policy(6, prev, cfg)
    assert a == b
    assert a.p2p_bonus_eur_per_kwh == round(
        min(R.MAX_BONUS, R.FIXED_BONUS + R.ADAPTIVE_GAIN * R.TARGET_P2P_SHARE), 5
    )
    assert a.p2p_bonus_eur_per_kwh > R.FIXED_BONUS


def test_adaptive_no_tradable_energy_does_not_react():
    cfg = C.SimConfig(regulator_mode="adaptive")
    prev = C.StepMetrics(step=5, tradable_kwh=0.0, p2p_potential_share=0.0)
    policy = R.get_policy(6, prev, cfg)
    assert policy.p2p_bonus_eur_per_kwh == R.FIXED_BONUS


def test_renewable_share_includes_local_market_netting_not_only_p2p():
    seller = C.ProsumerState(
        prosumer_id="P001", step=0, behaviour="green",
        pv_kwh=3.0, demand_kwh=1.0, pv_forecast_kwh=3.0,
        forecast_price=0.10, self_consumed_kwh=1.0,
        surplus_kwh=2.0, deficit_kwh=0.0,
    )
    buyer = C.ProsumerState(
        prosumer_id="P002", step=0, behaviour="conservative",
        pv_kwh=0.0, demand_kwh=3.0, pv_forecast_kwh=0.0,
        forecast_price=0.20, self_consumed_kwh=0.0,
        surplus_kwh=0.0, deficit_kwh=3.0,
    )
    orders = [
        C.Order("S",0,"P001",C.SIDE_SELL,2.0,0.10,"green"),
        C.Order("B",0,"P002",C.SIDE_BUY,3.0,0.20,"conservative"),
    ]
    market = C.MarketResult(
        step=0,
        transactions=[
            C.Transaction("LS",0,C.AGGREGATOR_ID,"P001",2.0,0.18,C.MARKET_LOCAL),
            C.Transaction("LB",0,"P002",C.AGGREGATOR_ID,3.0,0.22,C.MARKET_LOCAL),
        ],
        residual_import_kwh=1.0,
        residual_export_kwh=0.0,
    )
    m = M.evaluate(0,[seller,buyer],orders,market,C.Policy(step=0))
    # 3 kWh of the 4 kWh community demand is covered by community PV,
    # even though the 2 surplus kWh were routed through the aggregator.
    assert m.renewable_share == 0.75
    assert m.p2p_kwh == 0.0


def test_chart_generation(tmp_path):
    from gridshare import charts
    data = {
        "baseline": [C.StepMetrics(step=0, tradable_kwh=10, p2p_kwh=4, p2p_potential_share=.4)],
        "adaptive": [C.StepMetrics(step=0, tradable_kwh=10, p2p_kwh=8, p2p_potential_share=.8)],
    }
    paths = charts.make_charts(data, str(tmp_path))
    assert len(paths) == len(charts.SERIES) + 1
    assert all(Path(path).exists() for path in paths)
