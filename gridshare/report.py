"""Member 4 - self-contained HTML report of a demo run.

`run_demo.py` calls build_report() at the end of every run. The result is ONE
file (results/report.html) with everything embedded (CSS and charts as base64
images), so it can be opened offline, e-mailed, or shown at the presentation
as a backup of the live demo. Only the Python standard library is used.
"""
from __future__ import annotations

import base64
import html
import os
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .contract import SimulationResult

CHART_TITLES = {
    "p2p_kwh": "P2P traded energy per hour",
    "p2p_potential_share": "P2P share of the locally tradable energy",
    "grid_import_kwh": "Grid import by the aggregator",
    "community_cost_eur": "Community energy cost paid to the aggregator (negative = net revenue)",
    "regulator_bonus_eur": "Regulator bonus paid to P2P sellers",
    "energy_profile": "Community energy profile (first scenario)",
}

CSS = """
:root { --bg:#f7f8fa; --card:#fff; --ink:#1d2330; --muted:#5b6475; --line:#e3e6ec;
        --ok:#1a7f37; --ok-bg:#e6f4ea; --bad:#b42318; --bad-bg:#fdecea; --accent:#1f4e79; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
main { max-width:1100px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:26px; margin:0 0 4px; color:var(--accent); }
h2 { font-size:20px; margin:32px 0 12px; border-bottom:2px solid var(--line); padding-bottom:6px; }
h3 { font-size:16px; margin:20px 0 8px; }
.sub { color:var(--muted); margin:0 0 16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px; margin:12px 0; }
.verdict { font-size:18px; font-weight:700; padding:12px 16px; border-radius:8px; margin:16px 0; }
.verdict.ok { background:var(--ok-bg); color:var(--ok); }
.verdict.bad { background:var(--bad-bg); color:var(--bad); }
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:13px; font-weight:600; }
.badge.ok { background:var(--ok-bg); color:var(--ok); }
.badge.bad { background:var(--bad-bg); color:var(--bad); }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { background:#eef2f7; font-weight:600; }
td.l, th.l { text-align:left; }
code, .mono { font-family:Consolas, "SFMono-Regular", Menlo, monospace; font-size:13px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(480px, 100%), 1fr)); gap:16px; }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px; }
figure img { width:100%; height:auto; display:block; }
figcaption { color:var(--muted); font-size:13px; padding:4px 4px 0; }
details { margin:8px 0; }
summary { cursor:pointer; font-weight:600; color:var(--accent); }
.note { color:var(--muted); font-size:14px; }
.kv td { text-align:left; white-space:normal; vertical-align:top; }
.kv td:first-child { color:var(--muted); width:30%; padding-right:24px; }
.checks td:first-child { white-space:normal; min-width:160px; }
.err { color:var(--bad); }
@media (max-width:600px) { .kv td:first-child { width:40%; } .kv td { word-break:break-word; } }
"""


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _badge(ok: bool, yes: str = "PASS", no: str = "FAIL") -> str:
    return f'<span class="badge {"ok" if ok else "bad"}">{_e(yes if ok else no)}</span>'


def _img(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
    return f"data:image/png;base64,{data}"


def _checks(entry: Dict) -> List[Tuple[str, bool, str]]:
    res: SimulationResult = entry["result"]
    ok_t, errs_t, what_t = entry["tamper"]
    s = entry["summary"]
    tamper_detected = (not ok_t) or not res.ledger.chain
    return [
        ("Course minimum: 24+ steps, 10+ validators",
         s["steps"] >= 24 and s["validators"] >= 10,
         f"{s['steps']} steps, {s['validators']} validators, {s['prosumers']} prosumers"),
        ("Blockchain valid (hashes, links, signatures, quorum, stakes)", res.chain_valid,
         "; ".join(res.chain_errors[:3]) if res.chain_errors else f"{s['n_blocks']} blocks verified"),
        ("Every agreed trade recorded on the chain", res.all_trades_on_chain,
         f"{s['n_transactions_on_chain']} transactions on chain"),
        ("Tamper test: a modified trade is detected", tamper_detected,
         f"{what_t} → {errs_t[0] if errs_t else 'not detected'}"),
        ("Energy balance: PV + import − export = demand", res.energy_balance_ok, "checked every hour"),
    ]


def _comparison(summaries: Sequence[Dict]) -> str:
    cols = [
        ("scenario", "Scenario", "{}"),
        ("regulator_mode", "Regulator", "{}"),
        ("total_pv_kwh", "PV kWh", "{:.1f}"),
        ("total_demand_kwh", "Demand kWh", "{:.1f}"),
        ("p2p_kwh", "P2P kWh", "{:.1f}"),
        ("p2p_of_tradable", "P2P / tradable", "{:.1%}"),
        ("n_banned_total", "Bans", "{}"),
        ("grid_import_kwh", "Grid import kWh", "{:.1f}"),
        ("community_cost_eur", "Energy cost EUR", "{:.2f}"),
        ("regulator_bonus_eur", "Bonus EUR", "{:.2f}"),
        ("n_transactions_on_chain", "Tx on chain", "{}"),
    ]
    head = "".join(f"<th>{_e(t)}</th>" for _, t, _ in cols)
    rows = []
    for s in summaries:
        cells = "".join(f"<td>{_e(fmt.format(s[k]))}</td>" for k, _, fmt in cols)
        rows.append(f"<tr>{cells}</tr>")
    return f'<div class="scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>'


def _hourly(res: SimulationResult) -> str:
    cols = [("step", "Hour", "{}"), ("total_pv_kwh", "PV", "{:.2f}"), ("total_demand_kwh", "Demand", "{:.2f}"),
            ("p2p_kwh", "P2P", "{:.2f}"), ("tradable_kwh", "Tradable", "{:.2f}"),
            ("local_buy_kwh", "Local buy", "{:.2f}"), ("local_sell_kwh", "Local sell", "{:.2f}"),
            ("grid_import_kwh", "Import", "{:.2f}"), ("n_p2p_trades", "P2P trades", "{}"),
            ("n_banned", "Banned", "{}"), ("block_hash", "Block hash", "{}")]
    head = "".join(('<th class="l">' if k == "block_hash" else "<th>") + f"{_e(t)}</th>" for k, t, _ in cols)
    rows = []
    for m in res.metrics:
        cells = []
        for k, _, fmt in cols:
            v = getattr(m, k)
            if k == "block_hash":
                cells.append(f'<td class="l mono">{_e(str(v)[:16])}…</td>')
            else:
                cells.append(f"<td>{_e(fmt.format(v))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (f'<p class="note">Energy in kWh per hour.</p>'
            f'<div class="scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>')


def _blockchain(res: SimulationResult, n_last: int = 5) -> str:
    chain = res.ledger
    proposed = Counter(b.proposer_id for b in chain.chain)
    initial = chain.initial_stakes
    vrows = []
    for vid, v in sorted(chain.validators.items()):
        vrows.append(f"<tr><td>{_e(vid)}</td><td>{initial.get(vid, 0):.0f}</td><td>{v.stake:.0f}</td>"
                     f"<td>{proposed.get(vid, 0)}</td><td class='l'>{'faulty (never signs)' if v.faulty else 'honest'}</td></tr>")
    brows = []
    for b in chain.chain[-n_last:]:
        n_p2p = sum(1 for t in b.transactions if t["market_type"] == "P2P")
        brows.append(f"<tr><td>#{b.index}</td><td>{b.step}</td><td class='l mono'>{_e(b.block_hash[:20])}…</td>"
                     f"<td class='l mono'>{_e(b.prev_hash[:12])}…</td><td>{_e(b.proposer_id)}</td>"
                     f"<td>{len(b.transactions)} ({n_p2p} P2P)</td><td>{len(b.signatures)}/{len(chain.validators)}</td></tr>")
    return (
        "<h3>Validators (Proof-of-Stake)</h3>"
        '<div class="scroll"><table><tr><th>Validator</th><th>Initial stake</th><th>Final stake</th>'
        f"<th>Blocks proposed</th><th class='l'>Status</th></tr>{''.join(vrows)}</table></div>"
        f"<h3>Last {min(n_last, len(chain.chain))} blocks</h3>"
        '<div class="scroll"><table><tr><th>Block</th><th>Hour</th><th class="l">Hash</th>'
        '<th class="l">Previous hash</th><th>Proposer</th><th>Transactions</th><th>Signatures</th></tr>'
        f"{''.join(brows)}</table></div>"
        '<p class="note">A block is final when validators holding more than 2/3 of the stake have signed it. '
        "The proposer is chosen by stake-weighted random selection and receives a small stake reward.</p>"
    )


def build_report(entries: Sequence[Dict], chart_paths: Sequence[str], out_path: str,
                 command: str = "", all_passed: bool = True) -> str:
    """entries: one dict per scenario with keys 'summary', 'result', 'tamper' (ok, errors, description)."""
    if not entries:
        raise ValueError("no scenario results to report")
    first: SimulationResult = entries[0]["result"]
    checks_ok = all(ok for e in entries for _, ok, _ in _checks(e))
    all_passed = all_passed and checks_ok
    stubs = [k for k, v in first.module_sources.items() if v.startswith("stub")]

    parts: List[str] = []
    parts.append("<h1>GridShare 100 – simulation report</h1>")
    parts.append(f'<p class="sub">Generated {datetime.now():%d/%m/%Y %H:%M} · '
                 f"{first.config.n_prosumers} prosumers · {first.config.n_steps} hourly steps · "
                 f"{first.config.n_validators} validators · seed {first.config.seed}"
                 + (f" · <code>{_e(command)}</code>" if command else "") + "</p>")
    parts.append(f'<div class="verdict {"ok" if all_passed else "bad"}">'
                 f'{"ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED"}</div>')
    if stubs:
        parts.append('<div class="card note"><b>Placeholder modules in use:</b> '
                     f'{_e(", ".join(stubs))}. These parts still run on the stub implementations '
                     "(synthetic data), so the numbers are illustrative until the real modules are merged.</div>")

    # comparison
    parts.append("<h2>Scenario comparison</h2>")
    parts.append(_comparison([e["summary"] for e in entries]))
    parts.append('<p class="note"><b>P2P / tradable</b> = energy traded between neighbours ÷ energy that could '
                 "have been traded locally (min of total surplus and total deficit in each hour). "
                 "Without storage, grid import equals demand − PV and is fixed by physics: the regulator "
                 "changes <i>how</i> energy is traded (P2P vs aggregator), not how much is imported.</p>")

    # checks
    parts.append("<h2>Automatic checks</h2>")
    head = "<tr><th class='l'>Check</th>" + "".join(f"<th>{_e(e['summary']['scenario'])}</th>" for e in entries) + "</tr>"
    per = [_checks(e) for e in entries]
    rows = []
    for i, (name, _, _) in enumerate(per[0]):
        cells = "".join(f"<td title='{_e(p[i][2])}'>{_badge(p[i][1])}</td>" for p in per)
        rows.append(f"<tr><td class='l'>{_e(name)}</td>{cells}</tr>")
    parts.append(f'<div class="scroll"><table class="checks">{head}{"".join(rows)}</table></div>')
    parts.append('<p class="note">Hover a badge for details; failures are also explained in the scenario details below.</p>')

    # charts
    imgs = [(p, _img(p)) for p in chart_paths]
    imgs = [(p, d) for p, d in imgs if d]
    parts.append("<h2>Charts</h2>")
    if imgs:
        figs = []
        for p, d in imgs:
            key = os.path.splitext(os.path.basename(p))[0]
            title = CHART_TITLES.get(key, key.replace("_", " "))
            figs.append(f'<figure><img src="{d}" alt="{_e(title)}"><figcaption>{_e(title)}</figcaption></figure>')
        parts.append(f'<div class="grid">{"".join(figs)}</div>')
    else:
        parts.append('<p class="note">No charts (run without <code>--no-charts</code> and with matplotlib installed).</p>')

    # per scenario
    parts.append("<h2>Scenario details</h2>")
    for e in entries:
        res: SimulationResult = e["result"]
        s = e["summary"]
        ok_t, errs_t, what_t = e["tamper"]
        cfg = res.config
        parts.append(f'<div class="card"><h3>{_e(s["scenario"])} '
                     f'<span class="note">regulator = {_e(cfg.regulator_mode)}, PV scale = {cfg.pv_scale}</span></h3>')
        parts.append('<table class="kv">'
                     f"<tr><td class='l'>P2P trades / LOCAL trades</td><td>{s['n_p2p_trades']} / {s['n_local_trades']}</td></tr>"
                     f"<tr><td class='l'>Blocks / transactions on chain</td><td>{s['n_blocks']} / {s['n_transactions_on_chain']}</td></tr>"
                     f"<tr><td class='l'>Tamper test</td><td>{_e(what_t)} → "
                     f"{'detected: ' + _e(errs_t[0]) if errs_t else ('n/a' if not res.ledger.chain else 'NOT detected')}</td></tr>"
                     + "".join(f"<tr><td class='l err'>Check failed</td><td class='err'>{_e(name)}: {_e(detail)}</td></tr>"
                               for name, ok, detail in _checks(e) if not ok and not name.startswith("Blockchain valid"))
                     + "".join(f"<tr><td class='l err'>Chain error</td><td class='err'>{_e(err)}</td></tr>"
                               for err in res.chain_errors[:5])
                     + "</table>")
        parts.append(f"<details><summary>Hour by hour</summary>{_hourly(res)}</details>")
        parts.append(f"<details><summary>Blockchain</summary>{_blockchain(res)}</details>")
        parts.append("</div>")

    # modules
    parts.append("<h2>Modules used</h2>")
    mrows = "".join(f"<tr><td class='l'>{_e(k)}</td><td class='l'>{_e(v)}</td></tr>"
                    for k, v in first.module_sources.items())
    parts.append(f'<div class="scroll"><table><tr><th class="l">Module</th><th class="l">Implementation</th></tr>{mrows}</table></div>')
    parts.append('<p class="note">Raw data: <code>steps.csv</code>, <code>transactions.csv</code>, '
                 "<code>ledger.json</code> and <code>summary.json</code> in each scenario folder, "
                 "<code>comparison.csv</code> next to this report.</p>")

    doc = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>GridShare 100 report</title><style>{CSS}</style></head>"
           f"<body><main>{''.join(parts)}</main></body></html>")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path
