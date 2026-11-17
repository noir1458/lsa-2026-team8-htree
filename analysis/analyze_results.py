#!/usr/bin/env python3
"""Summarize completed HTree trials without treating queries as independent runs.

Primary metric: elapsed_ns / queries (the complete measured loop).
mean_ns in the input is a different metric: mean individually timed fstatat.
Policy/binary ratios are paired only within one patched run and round.
"""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import re
import statistics


def read_csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        yield from csv.DictReader(handle)


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def key_values(path):
    if not path.exists():
        return None
    return dict(part.split("=", 1) for part in path.read_text().split() if "=" in part)


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite number: %r" % value)
    return result


def describe(values, prefix):
    if not values:
        return {prefix + "_median": None, prefix + "_min": None, prefix + "_max": None}
    return {prefix + "_median": statistics.median(values),
            prefix + "_min": min(values), prefix + "_max": max(values)}


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as handle:
        if fields:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


class Analysis:
    def __init__(self, results, include_latencies=False):
        self.results = results
        self.include_latencies = include_latencies
        self.issues = []
        self.trials = []
        self.splits = []
        self.profiles = []
        self.inputs = []
        self.coverage = []

    def issue(self, path, code, detail, severity="warning"):
        self.issues.append({"source": str(path), "code": code,
                            "severity": severity, "detail": detail})

    def load_trials(self):
        for path in sorted(self.results.glob("*-n*/summary.csv")):
            match = re.fullmatch(r"(stock|patched)-n(\d+)", path.parent.name)
            if not match:
                continue
            self.inputs.append(str(path))
            phase, size = match.group(1), int(match.group(2))
            seen = set()
            raw_rows = list(read_csv(path))
            metadata = read_json(path.parent / "metadata.json")
            expected = None
            if metadata:
                expected = (int(metadata["rounds"]) * len(metadata["conditions"]) *
                            len(metadata["modes"].split(",")))
                if len(raw_rows) != expected:
                    self.issue(path, "incomplete_trial_matrix", "%d observed, %d planned" %
                               (len(raw_rows), expected), "error" if len(raw_rows) > expected else "warning")
            self.coverage.append({"dataset": path.parent.name, "observed_trials": len(raw_rows),
                                  "planned_trials": expected,
                                  "complete": len(raw_rows) == expected if expected is not None else None})
            for raw in raw_rows:
                try:
                    queries = int(raw["queries"])
                    elapsed = number(raw["elapsed_ns"])
                    trial = int(raw["trial"])
                    rep = int(raw["round"])
                    label, cache = raw["label"], raw["cache_mode"]
                    if queries <= 0 or elapsed <= 0:
                        raise ValueError("queries and elapsed_ns must be positive")
                except (KeyError, ValueError) as error:
                    self.issue(path, "invalid_trial", str(error), "error")
                    continue
                prefix = path.parent / ("trial_%04d_%s_%s" % (trial, label, cache))
                row = {"phase": phase, "directory_files": size, "dataset": path.parent.name,
                       "kernel": raw.get("kernel", ""), "label": label, "cache_mode": cache,
                       "round": rep, "trial": trial, "pass": int(raw.get("pass", 0)),
                       "queries": queries, "seed": raw.get("seed", ""),
                       "digest": raw.get("digest", ""), "elapsed_ns": elapsed,
                       "loop_ns_per_query": elapsed / queries,
                       "mean_syscall_ns": number(raw["mean_ns"]) if raw.get("mean_ns") else None,
                       "p50_syscall_ns": number(raw["p50_ns"]) if raw.get("p50_ns") else None,
                       "p95_syscall_ns": number(raw["p95_ns"]) if raw.get("p95_ns") else None,
                       "positive": int(raw["positive"]) if raw.get("positive") else None,
                       "negative": int(raw["negative"]) if raw.get("negative") else None,
                       "errors": int(raw.get("errors", -1)), "validation": "PASS",
                       "source": str(path), "prefix": str(prefix)}
                start = len(self.issues)
                cell = (rep, label, cache, row["pass"])
                if cell in seen:
                    self.issue(path, "duplicate_cell", str(cell), "error")
                seen.add(cell)
                if row["errors"] != 0:
                    self.issue(prefix, "benchmark_errors", str(row["errors"]), "error")
                if row["positive"] is not None and row["negative"] is not None:
                    if row["positive"] + row["negative"] != queries:
                        self.issue(prefix, "query_count_mismatch", "positive + negative != queries", "error")
                record = read_json(Path(str(prefix) + ".json"))
                if record is None:
                    self.issue(prefix, "missing_trial_record", "exit status and query preparation unverified")
                else:
                    if record.get("returncode") != 0:
                        self.issue(prefix, "trial_returncode", repr(record.get("returncode")), "error")
                    if str(record.get("query_seed", "")) != row["seed"]:
                        self.issue(prefix, "seed_record_mismatch", "CSV and trial JSON disagree", "error")
                policy = key_values(Path(str(prefix) + ".policy"))
                if phase == "patched":
                    if policy is None:
                        self.issue(prefix, "missing_policy", "profile-off state and actual policy unverified")
                    else:
                        if policy.get("profile_during_trial") not in ("0", "N", "n", "false"):
                            self.issue(prefix, "profiling_during_timing", repr(policy), "error")
                        expected = {"binary": "0", "linear": "1"}.get(label, "2" if label.startswith("hybrid") else None)
                        if expected is None or policy.get("search") != expected:
                            self.issue(prefix, "policy_mismatch", repr(policy), "error")
                        if label.startswith("hybrid") and policy.get("limit") != label[6:]:
                            self.issue(prefix, "threshold_mismatch", repr(policy), "error")
                    stats = key_values(Path(str(prefix) + ".stats"))
                    if stats is None:
                        self.issue(prefix, "missing_timing_stats", "zero profiling counters unverified")
                    elif not {"find", "nodes", "comparisons", "mismatches", "leaf_errors"}.issubset(stats):
                        self.issue(prefix, "incomplete_timing_stats", "required counters missing")
                    elif any(int(value) != 0 for value in stats.values()):
                        self.issue(prefix, "nonzero_timing_stats", repr(stats), "error")
                elif policy is not None:
                    self.issue(prefix, "stock_has_experiment_parameters", "stock identity needs checking", "error")
                if self.include_latencies:
                    self.load_latencies(row)
                new = self.issues[start:]
                if any(item["severity"] == "error" for item in new):
                    row["validation"] = "FAIL"
                elif new:
                    row["validation"] = "UNVERIFIED"
                self.trials.append(row)

    def load_latencies(self, trial):
        prefix = trial["prefix"]
        path = Path(prefix + ".latencies.csv")
        if not path.exists():
            path = Path(str(path) + ".gz")
        if not path.exists():
            self.issue(prefix, "missing_latencies", "optional per-query split unavailable")
            return
        samples = {0: [], 1: []}
        for row in read_csv(path):
            if int(row["pass"]) != trial["pass"]:
                continue
            exists = int(row["expected_exists"])
            latency = number(row["latency_ns"])
            if exists not in samples or latency < 0 or int(row["trial"]) != trial["trial"]:
                self.issue(path, "invalid_latency", repr(row), "error")
                continue
            samples[exists].append(latency)
        if sum(map(len, samples.values())) != trial["queries"]:
            self.issue(path, "latency_count_mismatch", "latencies != measured queries", "error")
        for exists, values in samples.items():
            expected = trial["positive" if exists else "negative"]
            if expected is not None and len(values) != expected:
                self.issue(path, "latency_class_count_mismatch", str(exists), "error")
            if values:
                self.splits.append({**{key: trial[key] for key in
                                    ("phase", "directory_files", "dataset", "kernel", "label", "cache_mode", "round", "trial", "pass")},
                                      "query_kind": "positive" if exists else "negative", "queries": len(values),
                                      "mean_syscall_ns": statistics.mean(values),
                                      "p50_syscall_ns": percentile(values, 50),
                                      "p95_syscall_ns": percentile(values, 95)})

    def load_profiles(self):
        for path in sorted(self.results.glob("profile-n*/*.stats")):
            match = re.fullmatch(r"profile-n(\d+)", path.parent.name)
            if not match:
                continue
            self.inputs.append(str(path))
            prefix = path.with_suffix("")
            record = read_json(Path(str(prefix) + ".json")) or {}
            policy = key_values(Path(str(prefix) + ".policy")) or {}
            stats = {key: int(value) for key, value in key_values(path).items()}
            start = len(self.issues)
            csv_path = Path(str(prefix) + ".csv")
            if not csv_path.exists():
                csv_path = Path(str(csv_path) + ".gz")
            trial_rows = list(read_csv(csv_path)) if csv_path.exists() else []
            queries = sum(int(row["queries"]) for row in trial_rows) or None
            if not trial_rows:
                self.issue(path, "missing_profile_trial_csv", "query count and benchmark errors unverified")
            if not {"nodes", "comparisons", "mismatches", "leaf_errors"}.issubset(stats):
                self.issue(path, "incomplete_profile_stats", "required counters missing")
            if any(int(row.get("errors", -1)) != 0 for row in trial_rows):
                self.issue(path, "profile_benchmark_errors", "nonzero/missing errors", "error")
            if record.get("returncode") != 0:
                self.issue(path, "profile_exit_unverified", repr(record.get("returncode")))
            if policy.get("profile_during_trial") not in ("1", "Y", "y", "true"):
                self.issue(path, "profile_state_unverified", repr(policy))
            for key in ("mismatches", "leaf_errors"):
                if stats.get(key, 0):
                    self.issue(path, "profile_" + key, str(stats[key]), "error")
            nodes = stats.get("nodes", 0)
            hist = {key: val for key, val in stats.items() if re.fullmatch(r"count_(?:\d+|\d+_\d+|513_plus)", key)}
            if sum(hist.values()) != nodes:
                self.issue(path, "histogram_total_mismatch", "histogram != nodes", "error")
            if stats.get("binary_nodes", 0) + stats.get("linear_nodes", 0) != nodes:
                self.issue(path, "node_total_mismatch", "binary + linear != nodes", "error")
            validation = "FAIL" if any(item["severity"] == "error" for item in self.issues[start:]) else "UNVERIFIED" if self.issues[start:] else "PASS"
            self.profiles.append({"source": str(path), "directory_files": int(match.group(1)),
                                  "label": record.get("condition", {}).get("label", trial_rows[0].get("label", "") if trial_rows else ""),
                                  "cache_mode": record.get("cache_mode", ""), "queries": queries,
                                  "validation": validation, **stats,
                                  "count_per_node": stats.get("count_sum", 0) / nodes if nodes else None,
                                  "comparisons_per_node": stats.get("comparisons", 0) / nodes if nodes else None,
                                  "dx_lookups_per_query": stats.get("dx_lookup", 0) / queries if queries else None,
                                  "leaf_entries_per_query": stats.get("leaf_entries", 0) / queries if queries else None})

    def summarize(self):
        groups = {}
        for row in self.trials:
            if row["validation"] == "FAIL":
                continue
            key = tuple(row[field] for field in ("phase", "directory_files", "dataset", "kernel", "cache_mode", "label"))
            groups.setdefault(key, []).append(row)
        summaries = []
        for key, rows in sorted(groups.items()):
            item = dict(zip(("phase", "directory_files", "dataset", "kernel", "cache_mode", "label"), key))
            item.update(trials=len(rows), unique_rounds=len({row["round"] for row in rows}),
                        validation="PASS" if all(row["validation"] == "PASS" for row in rows) else "UNVERIFIED")
            for metric in ("loop_ns_per_query", "mean_syscall_ns", "p50_syscall_ns", "p95_syscall_ns"):
                item.update(describe([row[metric] for row in rows if row[metric] is not None], metric))
            summaries.append(item)
        pairs = []
        binary = {}
        for row in self.trials:
            if row["phase"] == "patched" and row["label"] == "binary" and row["validation"] != "FAIL":
                key = (row["dataset"], row["kernel"], row["cache_mode"], row["round"], row["pass"])
                binary.setdefault(key, []).append(row)
        for row in self.trials:
            if row["phase"] != "patched" or row["label"] == "binary" or row["validation"] == "FAIL":
                continue
            key = (row["dataset"], row["kernel"], row["cache_mode"], row["round"], row["pass"])
            matches = binary.get(key, [])
            if len(matches) != 1:
                self.issue(row["prefix"], "no_unique_binary_pair", str(key))
                continue
            base = matches[0]
            if any(row[field] != base[field] for field in ("seed", "queries", "positive", "negative", "digest")):
                self.issue(row["prefix"], "paired_workload_mismatch", str(key), "error")
                continue
            ratio = row["loop_ns_per_query"] / base["loop_ns_per_query"]
            pairs.append({"directory_files": row["directory_files"], "dataset": row["dataset"],
                          "kernel": row["kernel"], "cache_mode": row["cache_mode"], "label": row["label"],
                          "round": row["round"], "pass": row["pass"], "seed": row["seed"],
                          "policy_trial": row["trial"], "binary_trial": base["trial"],
                          "policy_loop_ns_per_query": row["loop_ns_per_query"],
                          "binary_loop_ns_per_query": base["loop_ns_per_query"],
                          "policy_over_binary": ratio, "time_change_percent": (ratio - 1) * 100,
                          "validation": "PASS" if row["validation"] == base["validation"] == "PASS" else "UNVERIFIED"})
        paired_groups = {}
        for row in pairs:
            key = tuple(row[field] for field in ("directory_files", "dataset", "kernel", "cache_mode", "label"))
            paired_groups.setdefault(key, []).append(row)
        paired_summary = []
        for key, rows in sorted(paired_groups.items()):
            ratios = [row["policy_over_binary"] for row in rows]
            paired_summary.append({**dict(zip(("directory_files", "dataset", "kernel", "cache_mode", "label"), key)),
                                     "pairs": len(rows), **describe(ratios, "policy_over_binary"),
                                     "median_time_change_percent": (statistics.median(ratios) - 1) * 100,
                                     "faster_pairs": sum(ratio < 1 for ratio in ratios),
                                     "validation": "PASS" if all(row["validation"] == "PASS" for row in rows) else "UNVERIFIED"})
        return summaries, pairs, paired_summary

    def micro(self):
        path = self.results / "micro.csv"
        if not path.exists():
            return []
        self.inputs.append(str(path))
        groups = {}
        for row in read_csv(path):
            groups.setdefault((int(row["count"]), row["mode"]), []).append(number(row["ns_per_search"]))
        return [{"count": count, "mode": mode, "trials": len(values),
                 **describe(values, "ns_per_search"), "scope": "userspace_screening_only"}
                for (count, mode), values in sorted(groups.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--latencies", action="store_true", help="read optional per-query CSV or CSV.gz and split positive/negative")
    args = parser.parse_args()
    analysis = Analysis(args.results.resolve(), args.latencies)
    analysis.load_trials()
    analysis.load_profiles()
    summaries, pairs, paired_summary = analysis.summarize()
    micro = analysis.micro()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"timing_trials.csv": analysis.trials, "timing_summary.csv": summaries,
                 "paired_trials.csv": pairs, "paired_summary.csv": paired_summary,
                 "profile_summary.csv": analysis.profiles, "micro_summary.csv": micro,
                 "query_kind_trials.csv": analysis.splits}
    for name, rows in artifacts.items():
        write_csv(output / name, rows)
    errors = sum(item["severity"] == "error" for item in analysis.issues)
    report = {"status": "no_data" if not analysis.inputs else "validation_errors" if errors else "ok",
              "inputs": analysis.inputs, "timing_trials": len(analysis.trials),
              "coverage": analysis.coverage,
              "validation_errors": errors, "validation_warnings": len(analysis.issues) - errors,
              "issues": analysis.issues, "timing_summary": summaries, "paired_summary": paired_summary,
              "profile_summary": analysis.profiles, "micro_summary": micro,
              "notes": ["Primary timing is elapsed_ns / queries, not input mean_ns.",
                        "Percentiles in timing_summary are medians of trial percentiles, not pooled-query percentiles.",
                        "Queries within a trial are not independent experimental replications.",
                        "Paired ratios use the same patched dataset, kernel, cache mode, round, pass and query workload.",
                        "No stock/patched pairing or causal significance claim is made across separate boots.",
                        "FAIL trials are excluded from timing summaries; UNVERIFIED trials remain explicitly marked.",
                        "Profiling replays searches and must never supply performance timing.",
                        "Small effects require judging run-order drift and variability; min/max overlap is not an equivalence test."]}
    (output / "analysis_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "timing_trials": report["timing_trials"],
                      "errors": errors, "warnings": report["validation_warnings"]}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
