#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: run_profile.sh EXPERIMENT_DIR}
[[ -e /sys/module/ext4/parameters/htree_search ]] || exit 2
for n in 100 1000 10000 100000; do
  queries=$n
  (( queries > 10000 )) && queries=10000
  conditions=()
  for mode in binary linear hybrid4 hybrid8 hybrid16; do
    conditions+=(--condition "$mode=$root/fixtures/indexed/n$n")
  done
  HTREE_PROFILE=1 python3 "$root/scripts/bench_lookup.py" \
    --bench "$root/bench/lookup_bench" "${conditions[@]}" --files "$n" \
    --positive "$queries" --negative "$queries" --rounds 1 \
    --modes warmdir,warm --drop-caches 2 --cpu 0 \
    --before-hook "$root/scripts/bench_before.sh" --after-hook "$root/scripts/bench_after.sh" \
    --output "$root/results/profile-n$n"
done
