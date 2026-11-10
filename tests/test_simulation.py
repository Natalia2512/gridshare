"""Member 4 - end-to-end tests of the whole pipeline (the CI runs these)."""
import os
import sys
import types

import pytest

from gridshare import contract as C
from gridshare.simulation import SCENARIOS, config_for, load_modules, run_simulation, write_outputs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_full_run_meets_course_requirements(scenario):
    r = run_simulation(config_for(scenario, use_stubs=True))
    assert len(r.metrics) == 24 and len(r.blocks) == 24
    assert r.config.n_prosumers == 100
    assert r.chain_valid, r.chain_errors
    assert r.all_trades_on_chain
    assert r.energy_balance_ok
    assert len(r.ledger.validators) >= 10
    assert all(b.valid and len(b.validator_ids) >= 7 for b in r.blocks)
    types_ = {t.market_type for t in r.transactions}
    assert types_ == {C.MARKET_P2P, C.MARKET_LOCAL}


def test_reproducible_with_same_seed():
    a = run_simulation(config_for("adaptive", use_stubs=True))
    b = run_simulation(config_for("adaptive", use_stubs=True))
    assert [x.block_hash for x in a.blocks] == [x.block_hash for x in b.blocks]
    c = run_simulation(config_for("adaptive", use_stubs=True, seed=7))
    assert [x.block_hash for x in a.blocks] != [x.block_hash for x in c.blocks]


def test_longer_runs_supported_and_minimum_enforced():
    r = run_simulation(config_for("fixed", use_stubs=True, n_steps=48))
    assert len(r.blocks) == 48 and r.chain_valid
    with pytest.raises(ValueError):
        run_simulation(config_for("fixed", use_stubs=True, n_steps=23))


def test_regulator_changes_behaviour():
    base = run_simulation(config_for("baseline", use_stubs=True))
    fixed = run_simulation(config_for("fixed", use_stubs=True))
    p2p = lambda r: sum(m.p2p_kwh for m in r.metrics)
    assert p2p(fixed) > p2p(base)
    assert sum(m.n_banned for m in base.metrics) == 0
    assert sum(m.n_banned for m in fixed.metrics) > 0


def test_outputs_written(tmp_path):
    r = run_simulation(config_for("adaptive", use_stubs=True))
    paths = write_outputs(r, str(tmp_path))
    for p in paths.values():
        assert os.path.getsize(p) > 0


def test_real_module_replaces_stub(monkeypatch):
    """When a member adds gridshare/<module>.py it is picked up automatically."""
    from gridshare.stubs import trading_stub
    calls = []

    def clear_markets(step, orders, prosumers, policy, config):
        calls.append(step)
        return trading_stub.clear_markets(step, orders, prosumers, policy, config)

    fake = types.ModuleType("gridshare.trading")
    fake.clear_markets = clear_markets
    monkeypatch.setitem(sys.modules, "gridshare.trading", fake)
    _, _, sources = load_modules()
    assert sources["trading"].startswith("real")
    r = run_simulation(config_for("adaptive"))
    assert calls == list(range(24)) and r.chain_valid
    _, _, sources = load_modules(use_stubs=True)
    assert sources["trading"].startswith("stub")


def test_broken_module_is_caught_by_contract(monkeypatch):
    from gridshare.stubs import trading_stub

    def clear_markets(step, orders, prosumers, policy, config):
        m = trading_stub.clear_markets(step, orders, prosumers, policy, config)
        m.transactions = m.transactions[:-1]          # forgets one trade
        return m

    fake = types.ModuleType("gridshare.trading")
    fake.clear_markets = clear_markets
    monkeypatch.setitem(sys.modules, "gridshare.trading", fake)
    with pytest.raises(C.ContractError):
        run_simulation(config_for("adaptive"))


def test_demo_cli(tmp_path):
    sys.path.insert(0, ROOT)
    import run_demo
    rc = run_demo.main(["--scenario", "all", "--quiet", "--no-charts", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "comparison.csv").exists()
    assert (tmp_path / "adaptive" / "ledger.json").exists()


@pytest.mark.parametrize("args", [["--steps", "23"], ["--validators", "9"], ["--prosumers", "1"],
                                  ["--faulty-validators", "10"]])
def test_demo_cli_rejects_bad_arguments(args, tmp_path):
    sys.path.insert(0, ROOT)
    import run_demo
    with pytest.raises(SystemExit) as e:
        run_demo.main(args + ["--quiet", "--no-charts", "--out", str(tmp_path)])
    assert e.value.code == 2


def test_demo_cli_quorum_failure_is_clean(tmp_path, capsys):
    sys.path.insert(0, ROOT)
    import run_demo
    rc = run_demo.main(["--faulty-validators", "8", "--quiet", "--no-charts", "--out", str(tmp_path)])
    assert rc == 2 and "quorum" in capsys.readouterr().err
