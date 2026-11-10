"""STUB for Member 3 - result charts (matplotlib, optional).

If matplotlib is not installed the function returns an empty list and the
simulation keeps working (CSV/JSON results are always written).
"""
from __future__ import annotations

import os
from typing import Dict, List

from ..contract import StepMetrics

SERIES = [
    ("p2p_kwh", "P2P traded energy", "kWh"),
    ("p2p_potential_share", "P2P share of the locally tradable energy", "share"),
    ("grid_import_kwh", "Grid import by aggregator", "kWh"),
    ("community_cost_eur", "Community energy cost (paid to aggregator)", "EUR"),
    ("regulator_bonus_eur", "Regulator bonus paid to P2P sellers", "EUR"),
]


def make_charts(results: Dict[str, List[StepMetrics]], out_dir: str) -> List[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []
    for key, title, unit in SERIES:
        fig, ax = plt.subplots(figsize=(8, 4))
        for scen, metrics in results.items():
            ax.plot([m.step for m in metrics], [getattr(m, key) for m in metrics], marker="o",
                    markersize=3, label=scen)
        ax.set_title(title)
        ax.set_xlabel("time step (hour)")
        ax.set_ylabel(unit)
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        path = os.path.join(out_dir, f"{key}.png")
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths.append(path)

    # energy picture of the first scenario
    first = next(iter(results.values()))
    fig, ax = plt.subplots(figsize=(8, 4))
    steps = [m.step for m in first]
    ax.plot(steps, [m.total_pv_kwh for m in first], label="PV generation")
    ax.plot(steps, [m.total_demand_kwh for m in first], label="Demand")
    ax.bar(steps, [m.p2p_kwh for m in first], alpha=0.4, label="P2P traded")
    ax.set_title(f"Community energy ({next(iter(results))})")
    ax.set_xlabel("time step (hour)")
    ax.set_ylabel("kWh")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    path = os.path.join(out_dir, "energy_profile.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    paths.append(path)
    return paths
