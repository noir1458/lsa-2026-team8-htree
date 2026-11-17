#!/usr/bin/env python3
"""Render measured HTree results after analyze_results.py has validated them.

No placeholder measurements are generated. Min/max whiskers describe observed
trials and are not confidence intervals. Index-presence controls and search-
policy changes use separate panels and denominators.
"""
import argparse
import csv
import json
from pathlib import Path
import statistics


COLORS = {"binary": "#1f4e79", "linear": "#c65d21", "hybrid4": "#167c80",
          "hybrid8": "#386cb0", "hybrid16": "#8b5aa9"}
CACHES = ("warmdir", "warm")
CACHE_NAMES = {"warmdir": "Directory blocks warmed", "warm": "Repeated names warmed"}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def measured(rows):
    return [row for row in rows if row.get("validation", "PASS") == "PASS"]


def label_n(value):
    return "%dk" % (value // 1000) if value >= 1000 and value % 1000 == 0 else str(value)


def save(fig, output, name, description):
    fig.savefig(output / name, dpi=180, bbox_inches="tight",
                metadata={"Description": description})


def micro_figure(plt, report, results, output):
    summaries = report.get("micro_summary", [])
    raw = read_csv(results / "micro.csv")
    if not summaries or not raw:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), constrained_layout=True)
    for mode in ("binary", "linear"):
        rows = sorted((r for r in summaries if r["mode"] == mode), key=lambda r: r["count"])
        if not rows:
            continue
        x = [r["count"] for r in rows]
        y = [r["ns_per_search_median"] for r in rows]
        axes[0].errorbar(x, y, yerr=[[r["ns_per_search_median"] - r["ns_per_search_min"] for r in rows],
                                   [r["ns_per_search_max"] - r["ns_per_search_median"] for r in rows]],
                         marker="o", markersize=4, capsize=2, color=COLORS[mode], label=mode)
    cells = {}
    for row in raw:
        key = (int(row["count"]), int(row["round"]))
        cells.setdefault(key, {})[row["mode"]] = row
    ratios = {}
    for (count, rep), cell in cells.items():
        if "binary" not in cell or "linear" not in cell:
            continue
        b, l = cell["binary"], cell["linear"]
        for field in ("iterations", "checksum"):
            if field in b and field in l and b[field] != l[field]:
                raise ValueError("micro workload mismatch: count=%s round=%s" % (count, rep))
        ratios.setdefault(count, []).append(float(l["ns_per_search"]) / float(b["ns_per_search"]))
    x = sorted(ratios)
    y = [statistics.median(ratios[n]) for n in x]
    axes[1].errorbar(x, y, yerr=[[statistics.median(ratios[n]) - min(ratios[n]) for n in x],
                               [max(ratios[n]) - statistics.median(ratios[n]) for n in x]],
                     marker="o", markersize=4, capsize=2, color=COLORS["linear"])
    axes[1].axhline(1, color="#444444", linestyle="--", linewidth=1)
    for ax in axes:
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.set_xticks([1, 4, 16, 64, 256, 510])
        ax.set_xticklabels(["1", "4", "16", "64", "256", "510"])
        ax.set_xlabel("HTree index entries, including sentinel")
        ax.grid(True, alpha=.2)
    axes[0].set_ylabel("Time per search (ns)")
    axes[0].set_title("Userspace screening: absolute time")
    axes[0].legend(frameon=False)
    axes[1].set_ylabel("Linear / binary time (same round)")
    axes[1].set_title("Below 1: linear is faster")
    fig.suptitle("Search microbenchmark — not filesystem lookup performance", fontsize=12)
    fig.supxlabel("Points: trial medians; whiskers: observed min–max. Logarithmic axes.", fontsize=9)
    name = "fig1_micro_search.png"
    save(fig, output, name, "Measured userspace searches; min-max is not a confidence interval.")
    plt.close(fig)
    return name


def policy_panel(ax, rows, raw, cache):
    rows = [r for r in measured(rows) if r["cache_mode"] == cache]
    if not rows:
        ax.text(.5, .5, "No validated policy trials", ha="center", va="center", transform=ax.transAxes)
        return
    sizes = sorted({r["directory_files"] for r in rows})
    modes = [mode for mode in ("linear", "hybrid4", "hybrid8", "hybrid16")
             if any(r["label"] == mode for r in rows)]
    positions = {n: i for i, n in enumerate(sizes)}
    for j, mode in enumerate(modes):
        subset = sorted((r for r in rows if r["label"] == mode), key=lambda r: r["directory_files"])
        offset = (j - (len(modes) - 1) / 2) * .15
        x = [positions[r["directory_files"]] + offset for r in subset]
        y = [r["policy_over_binary_median"] for r in subset]
        ax.errorbar(x, y, yerr=[[r["policy_over_binary_median"] - r["policy_over_binary_min"] for r in subset],
                               [r["policy_over_binary_max"] - r["policy_over_binary_median"] for r in subset]],
                    marker="o", linestyle="none", capsize=3, markersize=5,
                    color=COLORS[mode], label=mode)
        for row in measured(raw):
            if row["label"] == mode and row["cache_mode"] == cache:
                jitter = ((int(row["round"]) % 7) - 3) * .009
                ax.scatter(positions[int(row["directory_files"])] + offset + jitter,
                           float(row["policy_over_binary"]), s=10, alpha=.25, color=COLORS[mode])
    ax.set_xticks(range(len(sizes)), [label_n(n) for n in sizes])
    lo = min(r["policy_over_binary_min"] for r in rows)
    hi = max(r["policy_over_binary_max"] for r in rows)
    ax.set_ylim(min(.9, lo * .98), max(1.1, hi * 1.02))
    ax.axhline(1, color="#444444", linestyle="--", linewidth=1)
    ax.set_xlabel("Files per directory")
    ax.set_ylabel("Policy / binary loop time per query")
    ax.set_title("Search-policy change: " + CACHE_NAMES.get(cache, cache))
    ax.grid(axis="y", alpha=.2)
    ax.legend(frameon=False, ncol=2, fontsize=8)


def control_panel(ax, rows, cache):
    rows = sorted((r for r in measured(rows) if r["cache_mode"] == cache), key=lambda r: r["directory_files"])
    if not rows:
        ax.text(.5, .5, "No validated index-presence control", ha="center", va="center", transform=ax.transAxes)
        return
    y = [r["indexed_over_unindexed_median"] for r in rows]
    ax.errorbar(range(len(rows)), y,
                yerr=[[r["indexed_over_unindexed_median"] - r["indexed_over_unindexed_min"] for r in rows],
                      [r["indexed_over_unindexed_max"] - r["indexed_over_unindexed_median"] for r in rows]],
                marker="s", linestyle="none", capsize=4, color="#44643b")
    ax.set_xticks(range(len(rows)), [label_n(r["directory_files"]) for r in rows])
    ax.axhline(1, color="#444444", linestyle="--", linewidth=1)
    if min(y) < .1:
        ax.set_yscale("log")
    ax.set_xlabel("Files per directory")
    ax.set_ylabel("Indexed / unindexed loop time per query")
    ax.set_title("HTree presence; binary policy fixed: " + CACHE_NAMES.get(cache, cache))
    ax.grid(axis="y", alpha=.2)


def actual_figure(plt, report, analysis_dir, output):
    policy = report.get("paired_summary", [])
    control = report.get("index_control_paired_summary", [])
    if not measured(policy) and not measured(control):
        return None
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    raw = read_csv(analysis_dir / "paired_trials.csv")
    for col, cache in enumerate(CACHES):
        policy_panel(axes[0, col], policy, raw, cache)
        control_panel(axes[1, col], control, cache)
    fig.suptitle("Filesystem lookup: two separate comparisons", fontsize=13)
    fig.supxlabel("Within-round ratios; medians and observed min–max, not confidence intervals. Profiling disabled.", fontsize=9)
    name = "fig2_actual_normalized.png"
    save(fig, output, name, "Search-policy ratios and index-presence ratios have separate denominators and panels.")
    plt.close(fig)
    return name


def cache_figure(plt, report, output):
    rows = measured(report.get("profile_summary", []))
    if not rows:
        return None
    # Do not pool different search policies or index configurations.
    selected = "binary" if any(r["label"] == "binary" for r in rows) else "indexed" if any(r["label"] == "indexed" for r in rows) else None
    if selected is None:
        return None
    rows = [r for r in rows if r["label"] == selected and r["queries"]]
    if not rows:
        return None
    sizes = sorted({r["directory_files"] for r in rows})
    positions = {n: i for i, n in enumerate(sizes)}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), constrained_layout=True)
    metrics = (("find", "ext4 find calls / query"), ("probe", "HTree probes / query"),
               ("leaf_entries", "Dirent records visited / query"))
    cache_colors = {"warmdir": "#386cb0", "warm": "#b06128"}
    for ax, (metric, title) in zip(axes, metrics):
        for j, cache in enumerate(CACHES):
            grouped = {}
            for row in rows:
                if row["cache_mode"] == cache:
                    grouped.setdefault(row["directory_files"], []).append(row[metric] / row["queries"])
            ns = sorted(grouped)
            if not ns:
                continue
            medians = [statistics.median(grouped[n]) for n in ns]
            ax.errorbar([positions[n] + (j - .5) * .12 for n in ns], medians,
                        yerr=[[statistics.median(grouped[n]) - min(grouped[n]) for n in ns],
                              [max(grouped[n]) - statistics.median(grouped[n]) for n in ns]],
                        marker="o", capsize=3, color=cache_colors[cache], label=CACHE_NAMES[cache])
        ax.set_xticks(range(len(sizes)), [label_n(n) for n in sizes])
        ax.set_xlabel("Files per directory")
        ax.set_title(title)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=.2)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Cache-state diagnostics — separate profiling runs, policy %s" % selected, fontsize=12)
    fig.supxlabel("Counts are instrumented function/record visits, not physical disk reads or a direct dcache hit-rate measurement.", fontsize=9)
    name = "fig3_cache_counts.png"
    save(fig, output, name, "Binary-policy profiling diagnostics; never used as timing samples.")
    plt.close(fig)
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    source = args.analysis / "analysis_summary.json"
    if not source.exists():
        parser.error("Run analyze_results.py on actual measurements first; no figures were generated.")
    report = json.loads(source.read_text())
    if report.get("validation_errors"):
        parser.error("Analysis has validation errors; repair or investigate before plotting.")
    if not any(report.get(key) for key in ("micro_summary", "paired_summary", "index_control_paired_summary", "profile_summary")):
        parser.error("No measured data are available; no figures were generated.")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    args.output.mkdir(parents=True, exist_ok=True)
    generated = [micro_figure(plt, report, args.results, args.output),
                 actual_figure(plt, report, args.analysis, args.output),
                 cache_figure(plt, report, args.output)]
    print(json.dumps({"generated": [name for name in generated if name]}))


if __name__ == "__main__":
    main()
