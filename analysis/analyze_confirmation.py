#!/usr/bin/env python3
"""Analyze the predeclared, separate confirmation session (no discovery pooling)."""
import argparse
import json
from pathlib import Path

from analyze_results import Analysis, read_json, write_csv


class ConfirmationAnalysis(Analysis):
    dataset_pattern = r"(confirm)-n(\d+)"
    timed_policy_phases = {"confirm"}
    paired_phases = {"confirm"}

    @staticmethod
    def expected_search(label):
        return {"binary": "0", "binary_shadow": "0", "linear": "1", "hybrid8": "2"}.get(label)

    def load_trials(self):
        super().load_trials()
        for size in (1000, 100000):
            directory = self.results / ("confirm-n%d" % size)
            rows = [row for row in self.trials if row["directory_files"] == size]
            start = len(self.issues)
            metadata = read_json(directory / "metadata.json")
            if metadata is None:
                self.issue(directory, "missing_confirmation_metadata", "predeclared plan unverified", "error")
            else:
                labels = {item["label"] for item in metadata.get("conditions", [])}
                if (metadata.get("rounds") != 20 or metadata.get("seed") != 20261119 or
                        metadata.get("modes") != "warmdir" or metadata.get("drop_caches") != 2 or
                        labels != {"binary", "binary_shadow", "linear", "hybrid8"}):
                    self.issue(directory, "confirmation_plan_mismatch", "expected 20 rounds, seed 20261119, warmdir/drop2, four planned labels", "error")
            planned_cells = {(rep, label, "warmdir", 0) for rep in range(20)
                             for label in ("binary", "binary_shadow", "linear", "hybrid8")}
            actual_cells = {(row["round"], row["label"], row["cache_mode"], row["pass"]) for row in rows}
            if actual_cells != planned_cells or len(rows) != 80:
                self.issue(directory, "confirmation_cell_coverage", "%d rows; %d missing and %d unexpected cells" %
                           (len(rows), len(planned_cells - actual_cells), len(actual_cells - planned_cells)), "error")
            if any(row["kernel"] != "5.4.214-htree1" for row in rows):
                self.issue(directory, "confirmation_kernel_mismatch", "expected 5.4.214-htree1", "error")
            if self.issues[start:]:
                for row in rows:
                    row["validation"] = "FAIL"


def tag_pairs(rows, baseline):
    for row in rows:
        for key in list(row):
            if key.startswith("policy_over_binary") or key in ("binary_trial", "binary_loop_ns_per_query"):
                row[key.replace("binary", "baseline")] = row.pop(key)
        row["baseline_label"] = baseline
        row["comparison_kind"] = ("same_policy_control" if row["label"] in ("binary", "binary_shadow")
                                  else "policy_change")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--latencies", action="store_true")
    args = parser.parse_args()
    analysis = ConfirmationAnalysis(args.results.resolve(), args.latencies)
    analysis.load_trials()
    summaries, pairs, paired_summary = analysis.summarize()
    tag_pairs(pairs, "binary")
    tag_pairs(paired_summary, "binary")

    # A second baseline checks sensitivity to the chosen binary replicate.
    # Preserve original trials and never pool separate boots or discovery data.
    original = analysis.trials
    analysis.trials = [{**row, "label": {"binary": "binary_shadow", "binary_shadow": "binary"}.get(row["label"], row["label"])}
                       for row in original]
    _, shadow_pairs, shadow_summary = analysis.summarize()
    analysis.trials = original
    for row in shadow_pairs + shadow_summary:
        if row["label"] == "binary_shadow":
            row["label"] = "binary"
    tag_pairs(shadow_pairs, "binary_shadow")
    tag_pairs(shadow_summary, "binary_shadow")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"confirmation_trials.csv": original, "confirmation_timing_summary.csv": summaries,
                 "confirmation_paired_trials.csv": pairs, "confirmation_paired_summary.csv": paired_summary,
                 "confirmation_shadow_paired_trials.csv": shadow_pairs,
                 "confirmation_shadow_paired_summary.csv": shadow_summary,
                 "confirmation_query_kind_trials.csv": analysis.splits}
    for name, rows in artifacts.items():
        write_csv(output / name, rows)
    errors = sum(issue["severity"] == "error" for issue in analysis.issues)
    report = {"status": "no_data" if not original else "validation_errors" if errors else "ok",
              "timing_trials": len(original), "coverage": analysis.coverage,
              "validation_errors": errors, "validation_warnings": len(analysis.issues) - errors,
              "issues": analysis.issues, "timing_summary": summaries,
              "paired_summary": paired_summary, "shadow_paired_summary": shadow_summary,
              "notes": ["Confirmation data are analyzed separately; discovery data are never replaced or pooled.",
                        "Plan: 20 rounds at n=1000 and n=100000, warmdir/drop_caches=2, seed=20261119.",
                        "Primary metric: complete loop elapsed_ns / queries; queries are not independent replications.",
                        "binary_shadow uses exactly search policy 0, making its ratio a same-policy variability control.",
                        "Main ratios use binary; shadow-reference ratios separately check sensitivity to the chosen replicate.",
                        "Shared denominators correlate same-round ratios; the two binary references are not independent effect replications.",
                        "Ranges are observed min/max, not confidence intervals or an equivalence claim.",
                        "No threshold is selected by filtering favorable trials. All validated planned trials remain."]}
    (output / "confirmation_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "timing_trials": len(original), "errors": errors,
                      "warnings": report["validation_warnings"]}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
