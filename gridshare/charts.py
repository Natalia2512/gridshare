"""Member 3 - scenario comparison charts for GridShare 100."""
from __future__ import annotations

import os
from typing import Dict, List

from .contract import StepMetrics
from .regulator import TARGET_P2P_SHARE

# field, title, y-axis label, is_share
SERIES = [
    ("p2p_potential_share", "P2P utilisation of locally tradable energy", "share", True),
    ("p2p_kwh", "P2P traded energy by hour", "kWh", False),
    ("grid_import_kwh", "External-grid import by hour", "kWh", False),
    ("community_cost_eur", "Community external-energy cost by hour", "EUR", False),
    ("regulator_bonus_eur", "Regulator P2P incentive cost by hour", "EUR", False),
    ("fairness_jain", "Buyer price fairness (Jain index)", "index", True),
    ("renewable_share", "Community demand served by local PV", "share", True),
]


def _save_line_chart(plt, results, key, title, ylabel, path, is_share=False):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for scenario, metrics in results.items():
        ax.plot(
            [m.step for m in metrics],
            [getattr(m, key) for m in metrics],
            marker="o",
            markersize=3,
            label=scenario,
        )
    if key == "p2p_potential_share":
        ax.axhline(TARGET_P2P_SHARE, linestyle="--", linewidth=1.2, label="adaptive target")
    ax.set_title(title)
    ax.set_xlabel("time step (hour)")
    ax.set_ylabel(ylabel)
    if is_share:
        ax.set_ylim(0.0, 1.05)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _scenario_totals_chart(plt, results, path):
    scenarios = list(results)
    values = []
    for scenario in scenarios:
        metrics = results[scenario]
        p2p = sum(m.p2p_kwh for m in metrics)
        tradable = sum(m.tradable_kwh for m in metrics)
        values.append(p2p / tradable if tradable > 1e-9 else 0.0)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(scenarios, values)
    ax.axhline(TARGET_P2P_SHARE, linestyle="--", linewidth=1.2, label="adaptive target")
    ax.set_title("Scenario comparison: P2P utilisation")
    ax.set_ylabel("P2P kWh / locally tradable kWh")
    ax.set_ylim(0.0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def make_charts(results: Dict[str, List[StepMetrics]], out_dir: str) -> List[str]:
    """Write comparison charts and return their file paths.

    The simulator can still run if matplotlib is unavailable; in that case an
    empty list is returned and CSV/JSON outputs remain available.
    """
    if not results:
        return []

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []

    for key, title, ylabel, is_share in SERIES:
        path = os.path.join(out_dir, f"{key}.png")
        _save_line_chart(plt, results, key, title, ylabel, path, is_share)
        paths.append(path)

    summary_path = os.path.join(out_dir, "scenario_p2p_utilisation.png")
    _scenario_totals_chart(plt, results, summary_path)
    paths.append(summary_path)

    return paths
