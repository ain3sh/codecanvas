from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class RunRow:
    task_id: str
    profile: str
    success: bool
    total_tokens_m: float
    backtrack_count: float
    elapsed_min: float
    total_steps: float


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def load_metrics_detail(path: Path) -> Dict[Tuple[str, str], RunRow]:
    with path.open() as f:
        reader = csv.DictReader(f)
        rows: Dict[Tuple[str, str], RunRow] = {}
        for row in reader:
            task_id = row["task_id"]
            profile = row["profile_key"]
            rows[(task_id, profile)] = RunRow(
                task_id=task_id,
                profile=profile,
                success=_parse_bool(row["success"]),
                total_tokens_m=float(row["total_tokens"]) / 1e6,
                backtrack_count=float(row["backtrack_count"]),
                elapsed_min=float(row["elapsed_sec"]) / 60.0,
                total_steps=float(row["total_steps"]),
            )
    return rows


def load_tool_distributions(path: Path) -> Dict[Tuple[str, str], Dict[str, int]]:
    with path.open() as f:
        reader = csv.DictReader(f)
        rows: Dict[Tuple[str, str], Dict[str, int]] = {}
        for row in reader:
            task_id = row["task_id"]
            profile = row["profile_key"]
            raw = row.get("tool_distribution")
            if not raw:
                rows[(task_id, profile)] = {}
                continue
            rows[(task_id, profile)] = {k: int(v) for k, v in json.loads(raw).items()}
    return rows


def mixed_rows(prev: Dict[Tuple[str, str], RunRow], latest: Dict[Tuple[str, str], RunRow]) -> Dict[Tuple[str, str], RunRow]:
    out: Dict[Tuple[str, str], RunRow] = {}
    for (task_id, profile) in prev.keys():
        if profile in {"text", "codecanvas"}:
            out[(task_id, profile)] = prev[(task_id, profile)]
    for (task_id, profile) in latest.keys():
        if profile == "codegraph":
            out[(task_id, profile)] = latest[(task_id, profile)]
    return out


def ensure_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    return plt, np


def save_per_task_heatmap(
    rows: Dict[Tuple[str, str], RunRow],
    tasks: List[str],
    profiles: List[str],
    out_path: Path,
):
    plt, np = ensure_matplotlib()
    from matplotlib.colors import LogNorm

    data = np.array([[rows[(task, prof)].total_tokens_m for prof in profiles] for task in tasks])
    vmin = max(0.05, float(data[data > 0].min()))
    vmax = float(data.max())

    task_labels = {
        "sanitize-git-repo": "sanitize",
        "build-cython-ext": "cython-ext",
        "custom-memory-heap-crash": "heap-crash",
        "db-wal-recovery": "wal-recovery",
        "modernize-scientific-stack": "modernize",
        "rstan-to-pystan": "rstan→pystan",
        "fix-code-vulnerability": "vuln-fix",
    }

    fig, ax = plt.subplots(figsize=(3.35, 3.05), constrained_layout=True)
    im = ax.imshow(data, aspect="auto", cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax))

    ax.set_xticks(range(len(profiles)), labels=["Text", "LocAgent", "CodeCanvas"])
    ax.set_yticks(range(len(tasks)), labels=[task_labels.get(t, t) for t in tasks])
    ax.tick_params(axis="x", labelsize=9)
    ax.tick_params(axis="y", labelsize=8)

    log_vmin = math.log(vmin)
    log_vmax = math.log(vmax)

    for i, task in enumerate(tasks):
        for j, prof in enumerate(profiles):
            r = rows[(task, prof)]
            mark = "✓" if r.success else "×"
            log_x = math.log(max(r.total_tokens_m, 1e-9))
            frac = 0.5 if log_vmax == log_vmin else (log_x - log_vmin) / (log_vmax - log_vmin)
            ax.text(
                j,
                i,
                f"{mark} {r.total_tokens_m:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if frac >= 0.55 else "black",
            )

    # No colorbar: tokens are already annotated per-cell; background color is a quick visual cue.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)


def save_tokens_vs_backtrack_scatter(
    rows: Dict[Tuple[str, str], RunRow],
    tasks: List[str],
    profiles: List[str],
    out_path: Path,
):
    plt, np = ensure_matplotlib()

    palette = {"text": "#6b7280", "codegraph": "#2563eb", "codecanvas": "#16a34a"}
    markers = {"text": "o", "codegraph": "s", "codecanvas": "^"}
    labels = {"text": "Text-Only", "codegraph": "LocAgent", "codecanvas": "CodeCanvas"}

    y_cap = 10.0
    y_min = -1.0
    outliers: List[Tuple[float, float, str, bool]] = []

    fig, ax = plt.subplots(figsize=(3.35, 2.6), constrained_layout=True)
    for prof in profiles:
        xs: List[float] = []
        ys: List[float] = []
        succ: List[bool] = []
        for task in tasks:
            r = rows[(task, prof)]
            xs.append(r.total_tokens_m)
            ys.append(r.backtrack_count)
            succ.append(r.success)

        for x, y, s in zip(xs, ys, succ):
            if y > y_cap:
                outliers.append((x, y, prof, s))

        xs_a = np.array(xs)
        ys_a = np.minimum(np.array(ys), y_cap)
        succ_a = np.array(succ)

        ax.scatter(
            xs_a[~succ_a],
            ys_a[~succ_a],
            s=30,
            marker=markers[prof],
            facecolors="none",
            edgecolors=palette[prof],
            linewidths=1.2,
            label=f"{labels[prof]} (fail)",
        )
        ax.scatter(
            xs_a[succ_a],
            ys_a[succ_a],
            s=30,
            marker=markers[prof],
            color=palette[prof],
            linewidths=0.8,
            label=f"{labels[prof]} (pass)",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Tokens (M, log scale)")
    ax.set_ylabel("Backtracks")
    ax.set_ylim(y_min, y_cap)
    ax.grid(True, alpha=0.25)
    ax.spines["bottom"].set_linewidth(1.0)
    ax.spines["left"].set_linewidth(1.0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for x, y, prof, s in outliers:
        ax.annotate(
            f"{int(y)}",
            xy=(x, y_cap),
            xytext=(x, y_cap - 1.6),
            textcoords="data",
            ha="center",
            va="top",
            fontsize=7,
            color=palette[prof],
            arrowprops={"arrowstyle": "-|>", "lw": 0.8, "color": palette[prof]},
        )

    ax.legend(fontsize=6.5, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.92))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)


def save_tool_mix_stacked_bar(
    prev_tools: Dict[Tuple[str, str], Dict[str, int]],
    latest_tools: Dict[Tuple[str, str], Dict[str, int]],
    tasks: List[str],
    out_path: Path,
):
    plt, np = ensure_matplotlib()
    from collections import Counter

    profiles = ["text", "codegraph", "codecanvas"]
    labels = {"text": "Text-Only", "codegraph": "LocAgent", "codecanvas": "CodeCanvas"}

    def mixed_tool_counter(profile: str) -> Counter:
        source = prev_tools if profile in {"text", "codecanvas"} else latest_tools
        c: Counter = Counter()
        for t in tasks:
            c.update(source.get((t, profile), {}))
        return c

    grouped_order = ["Bash", "Read", "Grep", "Edit", "TodoWrite", "MCP", "Other"]
    grouped_colors = {
        "Bash": "#111827",
        "Read": "#2563eb",
        "Grep": "#0ea5e9",
        "Edit": "#f97316",
        "TodoWrite": "#a855f7",
        "MCP": "#16a34a",
        "Other": "#9ca3af",
    }

    totals = []
    grouped_by_profile = {p: Counter() for p in profiles}
    for p in profiles:
        dist = mixed_tool_counter(p)
        total = sum(dist.values())
        totals.append(total)
        for k, v in dist.items():
            if k.startswith("mcp__"):
                grouped_by_profile[p]["MCP"] += v
            elif k in {"Bash", "Read", "Grep", "Edit", "TodoWrite"}:
                grouped_by_profile[p][k] += v
            else:
                grouped_by_profile[p]["Other"] += v

    x = np.arange(len(profiles))
    fig, ax = plt.subplots(figsize=(3.35, 2.35), constrained_layout=True)
    bottom = np.zeros(len(profiles))

    for key in grouped_order:
        vals = np.array([grouped_by_profile[p].get(key, 0) for p in profiles], dtype=float)
        ax.bar(x, vals, bottom=bottom, color=grouped_colors[key], label=key)
        bottom += vals

    for i, total in enumerate(totals):
        ax.text(i, total + max(totals) * 0.02, str(total), ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x, [labels[p] for p in profiles])
    ax.set_ylabel("Tool calls")
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(0, max(totals) * 1.35)
    ax.legend(ncol=3, fontsize=6.5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.02))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate paper figures from mixed-batch analytics.")
    parser.add_argument(
        "--prev-detail",
        type=Path,
        default=Path("../prev_results/analytics/metrics_detail.csv"),
        help="Path to prev metrics_detail.csv (text + codecanvas).",
    )
    parser.add_argument(
        "--latest-detail",
        type=Path,
        default=Path("../results/analytics/metrics_detail.csv"),
        help="Path to latest metrics_detail.csv (codegraph).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("../paper/fig"),
        help="Output directory for figures.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    prev = load_metrics_detail(args.prev_detail)
    latest = load_metrics_detail(args.latest_detail)
    mixed = mixed_rows(prev, latest)

    prev_tools = load_tool_distributions(args.prev_detail)
    latest_tools = load_tool_distributions(args.latest_detail)

    tasks = [
        "sanitize-git-repo",
        "build-cython-ext",
        "custom-memory-heap-crash",
        "db-wal-recovery",
        "modernize-scientific-stack",
        "rstan-to-pystan",
        "fix-code-vulnerability",
    ]
    profiles = ["text", "codegraph", "codecanvas"]

    save_per_task_heatmap(mixed, tasks, profiles, args.out_dir / "per_task_heatmap.png")
    save_tokens_vs_backtrack_scatter(mixed, tasks, profiles, args.out_dir / "tokens_vs_backtrack.png")
    save_tool_mix_stacked_bar(prev_tools, latest_tools, tasks, args.out_dir / "tool_mix.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
