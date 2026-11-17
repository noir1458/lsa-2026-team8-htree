#!/usr/bin/env python3
"""Synthetic checks only; temporary fixtures never become measured artifacts."""
import csv
import json
import math
from pathlib import Path
import tempfile

from analyze_confirmation import ConfirmationAnalysis, tag_pairs


with tempfile.TemporaryDirectory(prefix="htree-confirmation-check-") as tmp:
    root = Path(tmp)
    for size in (1000, 100000):
        directory = root / ("confirm-n%d" % size)
        directory.mkdir()
        labels = ["binary", "binary_shadow", "linear", "hybrid8"]
        (directory / "metadata.json").write_text(json.dumps({
            "rounds": 20, "seed": 20261119, "modes": "warmdir", "drop_caches": 2,
            "conditions": [{"label": label} for label in labels]}))
        rows = []
        for rep in range(20):
            for index, label in enumerate(labels):
                trial = rep * 4 + index
                rows.append(dict(label=label, kernel="5.4.214-htree1", trial=trial, round=rep,
                                 seed=20261119 + rep, queries=2, positive=1, negative=1,
                                 errors=0, mean_ns=30, cache_mode="warmdir", digest="same",
                                 elapsed_ns=[200, 220, 240, 180][index]))
                prefix = directory / ("trial_%04d_%s_warmdir" % (trial, label))
                Path(str(prefix) + ".json").write_text(json.dumps({"returncode": 0, "query_seed": 20261119 + rep}))
                Path(str(prefix) + ".policy").write_text("search=%s limit=8 profile_during_trial=0" %
                                                        {"binary": "0", "binary_shadow": "0", "linear": "1", "hybrid8": "2"}[label])
                Path(str(prefix) + ".stats").write_text("find=0 nodes=0 comparisons=0 mismatches=0 leaf_errors=0")
        with (directory / "summary.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    analysis = ConfirmationAnalysis(root)
    analysis.load_trials()
    _, pairs, summary = analysis.summarize()
    tag_pairs(summary, "binary")
    assert not analysis.issues, analysis.issues
    assert len(analysis.trials) == 160 and len(pairs) == 120
    for row in summary:
        assert row["pairs"] == 20
        assert math.isclose(row["policy_over_baseline_median"], {"binary_shadow": 1.1, "linear": 1.2, "hybrid8": .9}[row["label"]])
        assert (row["comparison_kind"] == "same_policy_control") == (row["label"] == "binary_shadow")
    # The alias must actually set binary: a mislabeled linear run is rejected.
    (root / "confirm-n1000/trial_0001_binary_shadow_warmdir.policy").write_text("search=1 limit=8 profile_during_trial=0")
    analysis = ConfirmationAnalysis(root)
    analysis.load_trials()
    assert any(issue["code"] == "policy_mismatch" for issue in analysis.issues)
    _, _, summary = analysis.summarize()
    assert next(row for row in summary if row["directory_files"] == 1000 and row["label"] == "binary_shadow")["pairs"] == 19
    print("confirmation self-check passed: exact planned coverage, alias policy, paired ratios, separate control label, invalid alias exclusion")
