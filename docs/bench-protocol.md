# Directory lookup experiment protocol

This kit measures Linux 5.4.214 ext4 name lookup. It does not equate an enabled
filesystem feature with an indexed directory, or a dcache hit with an ext4 lookup.
The fixtures contain empty files: this is metadata lookup, not file-content I/O.

## Build and create fixtures

```sh
cc -O2 -Wall -Wextra -Werror -std=c11 bench/lookup_bench.c -o bench/lookup_bench
python3 scripts/setup_lookup_fixture.py --parent /mnt/indexed \
  --counts 100,1000,10000 --metadata results/fixture-indexed.json
python3 scripts/setup_lookup_fixture.py --parent /mnt/linear \
  --counts 100,1000,10000 --metadata results/fixture-linear.json
```

The caller must first prepare and mount fresh test images. This setup script
does not format, mount, unmount, delete, or reuse nonempty fixture directories.
It makes `n100`, `n1000`, and `n10000`. Each contains `file_00000000` through
`file_(N-1)`, created in the same seeded shuffled order on each filesystem.
Metadata records an SHA-256 of the insertion sequence. Matching hashes are a
check on fixture comparability; inode numbers and physical layouts will differ.
An interrupted setup leaves its partial directory intact and a retry refuses it.

Before timing, record kernel version, VM resources, compiler/version/flags,
mount options, backing-device information, filesystem feature flags, filesystem
block size, and each directory's actual inode flags and index layout. In this
kernel `is_dx()` requires BOTH the filesystem `dir_index` feature and the
directory inode's `INDEX` flag. A 100-entry directory can fit in one block and
remain unindexed on both filesystems: retain that as a small-directory control,
and label the filesystem configuration separately from actual directory state.
Keep the same other filesystem options (including metadata checksums/inline-data
configuration) and the same creation order for both conditions.

## The C workload

```sh
bench/lookup_bench --dir /mnt/indexed/n1000 --files 1000 \
  --positive 1000 --negative 1000 --seed 20261118 \
  --warm-dir --latencies results/example-latencies.csv
```

- A single process opens the parent directory once and calls
  `fstatat(dirfd, name, ..., AT_SYMLINK_NOFOLLOW)` for each query.
- Each generated positive filename is used once per pass. If fewer positive
  queries than files are requested, their IDs are selected from a seeded random
  permutation of the full file set, rather than only the start of the directory.
- Each negative filename is distinct within the pass and includes the seed.
  The mixed positive/negative query sequence is deterministically shuffled.
- `--names FILE` instead accepts `1 filename` or `0 filename` lines; names are
  individual path components. This permits exact replay. Such a manifest can
  include repeats, so uniqueness is the caller's responsibility in that mode.
- A positive query must return a regular file; a negative query must return
  `ENOENT`. Any unexpected result makes the process exit 1 and increments errors.
  This verifies existence/type, not identity against a pre-recorded inode map.
- The semantic digest encodes result classes and query order, not inode numbers.
  It should match across filesystem conditions with the same seed and workload.
- `--warmup N` performs N untimed passes over the SAME query set. This deliberately
  warms positive AND negative dentries. Warmup failures abort the experiment.
- `--repeat N` repeats the same measured query set in one process. Later passes
  reuse the cache and must not be called independent cold trials. The balanced
  driver uses a new process and one measured pass per trial.
- `--warm-dir` enumerates the directory via `readdir`/getdents before timing,
  without explicitly looking up/stat-ing child filenames. Its intended purpose
  is warm directory blocks with uncached child names. Actual kernel call counts
  remain the deciding check; this option alone does not prove cache state.

Output is one summary CSV row per measured pass and optional per-query CSV.
Quantiles use nearest rank. Per-query time includes the entire `fstatat` call and
clock overhead, not only disk wait or `ext4_search_dir`. Whole-pass elapsed time
also includes iteration, correctness checking, and digest accumulation. Use raw
per-query data to separate positive and negative distributions. Per-query p99
from 100 names is descriptive; do not overinterpret a few tail samples.

## Balanced trials and cache states

```sh
python3 scripts/bench_lookup.py --bench bench/lookup_bench \
  --condition indexed_fs=/mnt/indexed/n1000 \
  --condition linear_fs=/mnt/linear/n1000 \
  --files 1000 --rounds 6 --modes warmdir,warm --drop-caches 2 \
  --cpu 1 --before-hook scripts/before_lookup.sh \
  --after-hook scripts/after_lookup.sh --output results/n1000
```

`--drop-caches` is opt-in. `2` asks the guest to reclaim reclaimable dentries and
inodes; it does not guarantee all of them are gone. `3` additionally asks for
page-cache reclamation. The driver performs `sync` and the drop before starting
each measured process. It never drops caches during the query loop.

The modes are:

| mode | preparation inside the child | intended interpretation |
|---|---|---|
| `none` | no explicit warmup | cache state determined by external preparation |
| `warmdir` | directory enumeration only | directory blocks warm, target dentries intended cold |
| `warm` | directory enumeration plus one full query pass | positive/negative dentries warm |

To study fully cold guest directory-data access separately, use `--modes none
--drop-caches 3`; do not combine its results with warm-directory CPU comparisons.
Reading the raw loop device is NOT used as a substitute for warming filesystem
directory buffers. Neither drop operation flushes the host's physical caches.

Every round contains every condition/mode exactly once with the same query seed.
For each pair of rounds, the cell order is shuffled then reversed, balancing
early/late positions. Query seeds change between rounds. Each trial logs its
command, cache request, round, seed, raw samples, stderr and result. A failed
trial aborts the run and leaves its evidence intact. Existing result directories
must be empty; files are never silently overwritten with a new experiment.

Use at least two matched conditions and several rounds. Inspect round-level
medians/ranges and paired differences rather than treating thousands of queries
within one boot as thousands of independent experimental replications. In this
VM, scheduling and host activity can dominate very small differences.

## Exact kernel-counter boundaries

The C process supports two pipe handshakes, used by the Python driver:

1. Prepare query memory, open directory, enumerate/warm up as requested.
2. Write `R` to `--ready-fd`, then block reading `--start-fd`.
3. Driver calls the before hook, then sends the start byte.
4. Child measures queries; it does not write results/latency files yet.
5. Child writes `R` to `--done-fd`, then blocks reading `--release-fd`.
6. Driver calls the after hook and sends release; child then writes results.

Both hooks receive `PID trial_id label cache_mode output_prefix`. They can set a
PID filter, reset counters, and snapshot counters while excluding path setup,
enumeration, warmup, and output-file operations. The root coordinator supplies
hooks matching the instrumentation interface. Use process-filtered counters
where possible to exclude the driver and unrelated activity.

Required evidence: positive+negative mixed warmdir trials actually enter the
ext4 lookup path; warm trials should have few/no such entries. If counts conflict
with the intended cache interpretation, resolve that before claiming algorithm
speedups. Inspect index probes, leaf blocks visited and dirent comparisons along
with overall calls. Calibration/instrumentation runs establish mechanism;
measurement overhead must be disclosed or measured separately from timings.

## Correctness and stopping rules

- Zero existence/type errors, and matching semantic digests across equivalent
  conditions, are prerequisites for accepting a timing trial.
- Verify the actual `INDEX` state; do not label a nonindexed small directory as
  an HTree measurement solely because its filesystem supports `dir_index`.
- Do not claim an ext4 speedup from warm dcache timings when ext4 is bypassed.
- A tiny function-only gain that disappears in actual lookup is a useful
  negative result, not a reason to keep expanding filesystem changes.
- Do not infer host physical disk savings from guest counters or use `ls`/`find`
  traversal as a direct substitute for targeted filename lookup.

The separate dx-search microbenchmark tests predecessor-search semantics and
isolated CPU cost. It cannot establish ext4 end-to-end speedup by itself.
