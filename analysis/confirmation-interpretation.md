# Independent reading of the confirmation

The predeclared new-boot/new-seed session is complete: 160 trials, all PASS,
zero validation errors and zero warnings. Both directory sizes contain 20
rounds of four labels in `warmdir`. `binary_shadow` actually sets policy 0;
all timing has profiling off and zero profiling counters. Compressed raw
latency counts, benchmark errors, and paired query workload checks pass.

The following are medians of same-round elapsed-time-per-query ratios. They
are not ratios of the absolute timing medians, which can differ substantially
when trials fluctuate.

| Files | Policy vs binary | Median time change | Observed pair range | Faster pairs |
|---:|---|---:|---:|---:|
| 1,000 | Identical binary shadow | +4.50% | −19.49% to +50.06% | 7/20 |
| 1,000 | Linear | +0.18% | −23.03% to +28.42% | 10/20 |
| 1,000 | Hybrid8 | +1.28% | −25.22% to +27.71% | 8/20 |
| 100,000 | Identical binary shadow | +0.10% | −1.79% to +66.41% | 10/20 |
| 100,000 | Linear | +8.97% | +6.47% to +10.85% | 0/20 |
| 100,000 | Hybrid8 | −0.24% | −2.46% to +2.34% | 11/20 |

The 1,000-file measurements do not establish a search-policy improvement;
the identical binary control itself fluctuates appreciably. The 100,000-file
pure-linear penalty repeats in all 20 pairs against binary. Against the
second binary reference it is +8.62% in median and slower in 19/20 pairs;
that reference includes one unusually slow trial, which is retained.
The prior roughly 8.47% median penalty and this roughly 8.97% penalty are
separate-session results, not a pooled estimate or a universal guarantee.

Hybrid8 is −0.24% against binary and −0.53% against binary shadow at 100,000
files, with mixed pair directions. These data do not demonstrate a useful
or reproducible hybrid gain. They also do not prove exact performance
equivalence. The two references share trials, so their ratios are correlated
and cannot be counted as independent confirmation studies.

The supported conclusion is to retain binary as the measured baseline and
report the explored hypothesis honestly: the tested small-node hybrid did
not establish an improvement, while replacing large-node binary search with
linear search reproducibly increased end-to-end lookup time in this setup.
An unchanged baseline is an experimental conclusion, not a failed experiment.
