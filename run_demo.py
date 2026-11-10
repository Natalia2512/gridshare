#!/usr/bin/env python3
"""GridShare 100 - live demo / command-line entry point (Member 4).

Examples
    python run_demo.py                          # adaptive scenario, 24 steps
    python run_demo.py --scenario all           # baseline, fixed, adaptive, pv_shortage + comparison
    python run_demo.py --scenario baseline --steps 48 --seed 7
    python run_demo.py --use-stubs              # ignore real modules, use stubs only
    python run_demo.py --faulty-validators 2    # robustness: 2 validators refuse to sign
    python run_demo.py --no-open                # write results/report.html without opening it

At the end of every run an HTML report (results/report.html) is written and
opened in the browser (not on CI servers).
"""
from __future__ import annotations

import argparse
import csv
import os
import shlex
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path

from gridshare.contract import ContractError
from gridshare.report import build_report
from gridshare.simulation import (SCENARIOS, config_for, make_charts, run_simulation,
                                  summarise, write_outputs)

LINE = "-" * 100


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GridShare 100 prosumer community simulator")
    ap.add_argument("--scenario", default="adaptive", choices=sorted(SCENARIOS) + ["all"])
    ap.add_argument("--steps", type=int, default=24, help="time steps (>= 24), 1 step = 1 hour")
    ap.add_argument("--prosumers", type=int, default=100)
    ap.add_argument("--validators", type=int, default=10, help="PoS validators (>= 10)")
    ap.add_argument("--faulty-validators", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="results")
    ap.add_argument("--use-stubs", action="store_true")
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="do not print every step")
    ap.add_argument("--debug", action="store_true", help="show full Python tracebacks on errors")
    ap.add_argument("--no-report", action="store_true", help="do not write results/report.html")
    ap.add_argument("--no-open", action="store_true", help="write the report but do not open the browser")
    args = ap.parse_args(argv)
    if args.steps < 24:
        ap.error("--steps must be at least 24 (course requirement)")
    if args.validators < 10:
        ap.error("--validators must be at least 10 (course requirement)")
    if args.prosumers < 10:
        ap.error("--prosumers must be at least 10 (the course asks for about 100)")
    if not 0 <= args.faulty_validators < args.validators:
        ap.error("--faulty-validators must be between 0 and --validators - 1")
    try:
        return run(args)
    except ContractError as e:
        if args.debug:
            traceback.print_exc()
        print(f"\nINTERFACE ERROR (a module broke gridshare/contract.py): {e}", file=sys.stderr)
        print("run again with --debug for the full traceback", file=sys.stderr)
        return 2
    except ValueError as e:
        if "quorum" not in str(e) or args.debug:
            raise                      # a real bug (e.g. in a teammate's module): keep the traceback
        print(f"\nERROR: {e}", file=sys.stderr)
        print("hint: too many faulty validators - honest stake must exceed 2/3 of the total; "
              "try fewer --faulty-validators", file=sys.stderr)
        return 2


def run(args) -> int:

    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    all_metrics, summaries, entries, failed = {}, [], [], False
    report_path = os.path.join(args.out, "report.html")
    if os.path.exists(report_path):
        os.remove(report_path)   # never leave a previous run's report behind if this run crashes
    t0 = time.time()
    for scen in scenarios:
        cfg = config_for(scen, n_steps=args.steps, n_prosumers=args.prosumers, seed=args.seed,
                         n_validators=args.validators, faulty_validators=args.faulty_validators,
                         use_stubs=args.use_stubs)
        print(LINE)
        print(f"SCENARIO {scen.upper()} | regulator={cfg.regulator_mode} | PV scale={cfg.pv_scale} | "
              f"{cfg.n_prosumers} prosumers | {cfg.n_steps} steps | {cfg.n_validators} validators")
        print(LINE)
        res = run_simulation(cfg, log=None if args.quiet else print)
        if scen == scenarios[0]:
            print("modules used:", ", ".join(f"{k}={v}" for k, v in res.module_sources.items()))
        paths = write_outputs(res, os.path.join(args.out, scen))
        s = summarise(res)
        summaries.append(s)
        all_metrics[scen] = res.metrics

        ok_t, errs_t, what_t = res.ledger.tamper_demo()
        entries.append({"summary": s, "result": res, "tamper": (ok_t, errs_t, what_t)})
        print(f"\nblockchain: {s['n_blocks']} blocks, {s['n_transactions_on_chain']} transactions, "
              f"valid={res.chain_valid}, every agreed trade on chain={res.all_trades_on_chain}")
        print(f"tamper test: {what_t} -> chain valid={ok_t} "
              f"({errs_t[0] if errs_t else 'no error found!'})")
        if not res.chain_valid:
            for e in res.chain_errors[:5]:
                print("  chain error:", e)
        print(f"energy balance (PV + import - export = demand): {res.energy_balance_ok}")
        print(f"P2P {s['p2p_kwh']:.1f} kWh = {s['p2p_of_tradable']:.0%} of the locally tradable energy "
              f"({s['tradable_kwh']:.1f} kWh); grid import {s['grid_import_kwh']:.1f} kWh; "
              f"energy cost {s['community_cost_eur']:.2f} EUR, regulator bonus {s['regulator_bonus_eur']:.2f} EUR")
        print("results ->", os.path.dirname(paths["summary"]))
        if not (res.chain_valid and res.all_trades_on_chain and res.energy_balance_ok) or (ok_t and res.ledger.chain):
            failed = True

    if len(summaries) > 1:
        comp = os.path.join(args.out, "comparison.csv")
        os.makedirs(args.out, exist_ok=True)
        with open(comp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(summaries[0]))
            w.writeheader()
            w.writerows(summaries)
        print(LINE)
        print(f"{'scenario':<12}{'P2P kWh':>9}{'P2P/tradable':>14}{'banned':>8}{'import kWh':>12}"
              f"{'energy EUR':>12}{'bonus EUR':>11}{'tx on chain':>13}")
        for s in summaries:
            print(f"{s['scenario']:<12}{s['p2p_kwh']:>9.1f}{s['p2p_of_tradable']:>14.1%}"
                  f"{s['n_banned_total']:>8d}{s['grid_import_kwh']:>12.1f}"
                  f"{s['community_cost_eur']:>12.2f}{s['regulator_bonus_eur']:>11.2f}"
                  f"{s['n_transactions_on_chain']:>13d}")
        print("note: with no storage, grid import = demand - PV is physically fixed; the regulator "
              "changes HOW energy is traded (P2P vs aggregator), not how much is imported.")
        print("comparison ->", comp)

    charts = []
    if not args.no_charts:
        charts = make_charts(all_metrics, os.path.join(args.out, "charts"), args.use_stubs)
        print("charts ->", ", ".join(charts) if charts else "matplotlib not installed, charts skipped")
    if not args.no_report:
        cmd = "python run_demo.py " + quote_args(sys.argv[1:]) if argv_is_cli() else ""
        report = build_report(entries, charts, report_path, command=cmd, all_passed=not failed)
        print("report ->", report)
        if not args.no_open and not os.environ.get("CI"):
            try:
                webbrowser.open(Path(report).resolve().as_uri())
            except Exception:  # no browser available: the file is still there
                pass
    print(LINE)
    print(f"done in {time.time() - t0:.1f} s - {'ALL CHECKS PASSED' if not failed else 'SOME CHECKS FAILED'}")
    return 1 if failed else 0


def quote_args(args) -> str:
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def argv_is_cli() -> bool:
    return bool(sys.argv) and os.path.basename(sys.argv[0]) == "run_demo.py"


if __name__ == "__main__":
    sys.exit(main())
