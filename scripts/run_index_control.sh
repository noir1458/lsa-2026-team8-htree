#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: run_index_control.sh EXPERIMENT_DIR}
[[ -e /sys/module/ext4/parameters/htree_search ]] || exit 2
for n in 1000 10000; do
  HTREE_PROFILE=0 python3 "$root/scripts/bench_lookup.py" \
    --bench "$root/bench/lookup_bench" \
    --condition "indexed=$root/fixtures/indexed/n$n" \
    --condition "unindexed=$root/fixtures/linear/n$n" \
    --files "$n" --rounds 6 --modes warmdir,warm --drop-caches 2 --cpu 0 \
    --before-hook "$root/scripts/bench_before.sh" --after-hook "$root/scripts/bench_after.sh" \
    --output "$root/results/index-control-n$n"
done
