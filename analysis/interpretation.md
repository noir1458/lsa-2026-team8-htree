# Independent reading of the initial measurements

This note concerns the initial session only. A subsequent confirmation is
analyzed separately and does not replace these measurements.

## Validation

The analyzer reports zero errors and zero warnings. Coverage is complete:
80 stock timing trials, 400 patched timing trials, 48 index-presence control
trials, and 40 separate profiling trials. The microbenchmark contains 280
unique cells: 10 rounds × 14 entry counts × 2 policies. Patched and control
timing runs have profiling disabled and zero profiling counters. All benchmark
error fields, profiled search mismatches and profiled leaf errors are zero.
The compressed latency records match the planned query counts.

## What the controls establish

All 20 repeated-name (`warm`) profiles have `find=0`: those workloads bypass
the instrumented ext4 directory-search path. Their measured differences
cannot be attributed to the changed HTree node search. For 100 files,
`warmdir` enters ext4 but never HTree (`probe=0`); this is another useful
negative control. Several large percentage differences in these short trials
therefore reflect measurement/session variability rather than policy effects.

For the `warmdir` binary profiles, find calls equal queries at every size.
At 1,000 and larger sizes, HTree probes also equal queries. The 1,000-file
directory uses count 8, so linear, hybrid8 and hybrid16 select linear search;
the measured differences between those labels do not represent different
node-search algorithms. At 10,000 files the node count is 83, so every hybrid
threshold tested selects binary search. At 100,000 files each query visits a
count-2 node and a node in the 257–512 bucket; all three hybrid thresholds
make the same algorithm choice (linear for the small node, binary for the
large node).

## Search-policy result

In the userspace screening test, linear has no median advantage at any tested
entry count. Its same-round median time ratio to binary is about 1.13 at
count 8, 3.76 at count 83, and 14.1–16.1 at counts 436–510. This is supporting
screening evidence, not the kernel code's exact generated machine code.

In actual `warmdir` lookup, linear/binary median paired time is 1.0121 at
10,000 files (slower in all 10 pairs) and 1.0847 at 100,000 files (slower in
9 of 10 pairs). The second condition has a wide observed ratio range,
0.6387–1.3888, so the magnitude should not be presented as a stable universal
effect. Hybrid differences at these larger sizes are mostly within about
one percent and do not establish a practical improvement.

Profiling is consistent with the direction of the linear-search cost:

| Files | Binary comparisons | Linear comparisons | Queries | Same leaf records visited under both |
|---:|---:|---:|---:|---:|
| 1,000 | 6,000 | 8,309 | 2,000 | 192,008 |
| 10,000 | 129,006 | 802,366 | 20,000 | 1,899,968 |
| 100,000 | 196,717 | 4,453,768 | 20,000 | 1,790,241 |

These are diagnostic work counts from separate profiling runs, not time
fractions. Comparison counts alone cannot yield an Amdahl speedup estimate.

## Existing HTree value is a separate result

At fixed binary policy, indexed/unindexed median paired `warmdir` time ratios
are 0.1771 for 1,000 files and 0.02300 for 10,000 files: about 5.65× and 43.48×
speed ratios in these workloads. Those large effects demonstrate the value
of the existing directory index. They are not gains from this patch. The
same advantage is not established after repeated-name warming.

## Supported decision

The initial data do not support choosing linear or a hybrid threshold as a
demonstrated improvement. They do support a reproducible study of where the
existing HTree helps, when dentry caching bypasses it, and why replacing its
node search can increase work without improving end-to-end lookup. The
separate confirmation session with a same-policy shadow control is needed
to judge repeatability before interpreting small policy differences.

Do not infer zero instrumentation overhead from the separate stock boot:
boot/session differences and small-sample timing variability confound that
comparison. Do not interpret this workload as cold physical-disk I/O: its
directory blocks are intentionally warmed.
