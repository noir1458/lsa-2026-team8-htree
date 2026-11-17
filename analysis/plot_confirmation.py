#!/usr/bin/env python3
"""Plot only the separate measured confirmation session."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--analysis", type=Path, default=Path(__file__).resolve().parent)
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
args = parser.parse_args()
directory = args.analysis
args.output.mkdir(parents=True, exist_ok=True)
report = json.loads((directory / "confirmation_summary.json").read_text())
if report["status"] != "ok" or report["validation_errors"] or report["validation_warnings"]:
    raise SystemExit("Confirmation must pass validation before rendering.")
with (directory / "confirmation_paired_trials.csv").open(newline="") as handle:
    trials = list(csv.DictReader(handle))
summaries = report["paired_summary"]
labels = ["binary_shadow", "linear", "hybrid8"]
colors = {"binary_shadow": "#777777", "linear": "#c65d21", "hybrid8": "#386cb0"}
names = {"binary_shadow": "Binary shadow\n(same policy)", "linear": "Linear", "hybrid8": "Hybrid, threshold 8"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.7), sharey=True, constrained_layout=True)
lo = min(row["policy_over_baseline_min"] for row in summaries)
hi = max(row["policy_over_baseline_max"] for row in summaries)
for ax, size in zip(axes, (1000, 100000)):
    tick_names = []
    for pos, label in enumerate(labels):
        summary = next(row for row in summaries if row["directory_files"] == size and row["label"] == label)
        selected = [row for row in trials if int(row["directory_files"]) == size and row["label"] == label]
        for row in selected:
            jitter = ((int(row["round"]) % 7) - 3) * .016
            ax.scatter(pos + jitter, float(row["policy_over_baseline"]), color=colors[label], alpha=.38, s=18)
        median = summary["policy_over_baseline_median"]
        ax.errorbar(pos, median, yerr=[[median - summary["policy_over_baseline_min"]],
                                      [summary["policy_over_baseline_max"] - median]],
                    marker="D", markersize=6, capsize=5, color=colors[label])
        tick_names.append(names[label] + "\nMedian %+.2f%%" % summary["median_time_change_percent"])
    ax.axhline(1, color="#333333", linestyle="--", linewidth=1)
    ax.set_ylim(max(0, lo - .04), hi + .05)
    ax.set_xlim(-.45, 2.45)
    ax.set_xticks(range(len(labels)), tick_names, fontsize=9)
    ax.set_title("%s files; directory blocks warmed" % format(size, ","))
    ax.grid(axis="y", alpha=.2)
axes[0].set_ylabel("Complete loop time / binary time (same round)")
fig.suptitle("Separate confirmation: identical binary policy exposes timing variability", fontsize=12)
fig.supxlabel("20 pairs per policy and size, new boot and seed; profiling off. Dots: trials; diamonds: medians; whiskers: observed min–max.", fontsize=8)
path = args.output / "fig4_confirmation.png"
fig.savefig(path, dpi=180, bbox_inches="tight", metadata={"Description": "Separate confirmation data; same-policy shadow control, not pooled with initial trials."})
plt.close(fig)
print(path)
