# Analysis and figures

Run from the repository root with Python 3.8 or newer:

```sh
python3 analysis/check_analyzer.py
python3 analysis/check_confirmation.py
python3 analysis/analyze_results.py --latencies
python3 analysis/plot_results.py
python3 analysis/analyze_confirmation.py --latencies
python3 analysis/plot_confirmation.py
```

The analyzers use the Python standard library. Plotting additionally requires
Matplotlib (`python3 -m pip install matplotlib`). This run used Python 3.12.14
and Matplotlib 3.11.2. An isolated environment can be used for plotting;
no global Python installation needs to be changed. For newly collected data,
pass the explicit input and output directories described in
[`docs/reproduce.md`](../docs/reproduce.md).

`--latencies` reads both `.latencies.csv` and `.latencies.csv.gz`. Positive and
negative query summaries are stored separately, without treating individual
queries as independent experimental replications. The self-check scripts use
temporary synthetic fixtures that never become experiment result artifacts.

The primary metric is the complete measured loop's `elapsed_ns / queries`.
Input `mean_ns` is the mean of individually timed system calls and is reported
as a distinct metric. Policy comparisons use same-round ratios from the same
session, seed and query workload. Stock and patched kernels are separate boots
and are not paired as causal overhead estimates. Error or profiling-enabled
timing trials are excluded; missing verification is explicitly labeled.

`analysis_summary.json` and the unprefixed CSV files describe the initial
measurement session. `index_control_*` compares existing HTree presence at a
fixed binary policy, separately from changes to HTree node search.
`confirmation_*` describes the subsequent predeclared session only. Its main
ratios use `binary`; `confirmation_shadow_paired_*` uses `binary_shadow` as a
second reference. Both references execute the same binary policy, and the two
comparisons are correlated, not independent effect replications.

The PNG figures show measured medians and observed minimum–maximum ranges.
These ranges are not confidence intervals, and overlap is not an equivalence
test. The microbenchmark is a userspace screening implementation; its absolute
timings do not measure kernel filesystem lookup latency. Profile counts are
function or record visits, not physical I/O counts or a directly measured
dcache hit rate.
