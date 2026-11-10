"""Member 4 - HTML report tests."""
import os
import re
import sys

import pytest

from gridshare.report import build_report
from gridshare.simulation import config_for, run_simulation, summarise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def entry(scenario="adaptive", **kw):
    r = run_simulation(config_for(scenario, use_stubs=True, **kw))
    return {"summary": summarise(r), "result": r, "tamper": r.ledger.tamper_demo()}


def test_report_contains_key_sections(tmp_path):
    out = build_report([entry("baseline"), entry("adaptive")], [], str(tmp_path / "r.html"))
    text = open(out, encoding="utf-8").read()
    assert text.startswith("<!doctype html>")
    for s in ("ALL CHECKS PASSED", "Scenario comparison", "Automatic checks", "Validators",
              "baseline", "adaptive", "Modules used", "Placeholder modules in use"):
        assert s in text
    assert text.count("PASS</span>") == 2 * 5          # 5 checks x 2 scenarios
    assert "<script" not in text                        # static page, no JS


def test_report_is_self_contained_with_charts(tmp_path):
    from gridshare.simulation import make_charts
    e = entry()
    charts = make_charts({"adaptive": e["result"].metrics}, str(tmp_path / "charts"), use_stubs=True)
    out = build_report([e], charts, str(tmp_path / "r.html"))
    text = open(out, encoding="utf-8").read()
    if charts:
        assert text.count("data:image/png;base64,") == len(charts)
    assert not re.search(r'src="(?!data:)', text)       # no external files referenced


def test_report_marks_failures(tmp_path):
    e = entry()
    e["result"].chain_valid = False
    e["result"].chain_errors = ["block 3 (step 3): merkle root mismatch <script>"]
    out = build_report([e], [], str(tmp_path / "r.html"), all_passed=False)
    text = open(out, encoding="utf-8").read()
    assert "SOME CHECKS FAILED" in text and "FAIL</span>" in text
    assert "<script>" not in text and "&lt;script&gt;" in text   # error text is escaped


def test_report_without_entries_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_report([], [], str(tmp_path / "r.html"))


def test_demo_writes_report_and_respects_flags(tmp_path):
    sys.path.insert(0, ROOT)
    import run_demo
    assert run_demo.main(["--quiet", "--no-charts", "--no-open", "--out", str(tmp_path / "a")]) == 0
    assert (tmp_path / "a" / "report.html").exists()
    assert run_demo.main(["--quiet", "--no-charts", "--no-report", "--out", str(tmp_path / "b")]) == 0
    assert not (tmp_path / "b" / "report.html").exists()


def test_demo_does_not_open_browser_on_ci(tmp_path, monkeypatch):
    sys.path.insert(0, ROOT)
    import run_demo
    opened = []
    monkeypatch.setattr(run_demo.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setenv("CI", "true")
    run_demo.main(["--quiet", "--no-charts", "--out", str(tmp_path / "c")])
    assert opened == []
    monkeypatch.delenv("CI")
    run_demo.main(["--quiet", "--no-charts", "--out", str(tmp_path / "d")])
    assert len(opened) == 1 and opened[0].startswith("file:")


def test_verdict_follows_checks_and_failure_reason_visible(tmp_path):
    e = entry()
    e["result"].energy_balance_ok = False
    out = build_report([e], [], str(tmp_path / "r.html"))          # caller says all_passed=True
    text = open(out, encoding="utf-8").read()
    assert "SOME CHECKS FAILED" in text
    assert "Check failed" in text and "Energy balance" in text


def test_stale_report_removed_when_run_crashes(tmp_path, capsys):
    sys.path.insert(0, ROOT)
    import run_demo
    out = tmp_path / "x"
    assert run_demo.main(["--quiet", "--no-charts", "--no-open", "--out", str(out)]) == 0
    assert (out / "report.html").exists()
    assert run_demo.main(["--faulty-validators", "8", "--quiet", "--no-charts", "--no-open",
                          "--out", str(out)]) == 2
    assert not (out / "report.html").exists()


def test_quote_args_keeps_spaces():
    sys.path.insert(0, ROOT)
    import run_demo
    q = run_demo.quote_args(["--out", "my dir/x"])
    assert '"my dir/x"' in q or "'my dir/x'" in q
