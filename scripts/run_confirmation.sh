#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: run_confirmation.sh EXPERIMENT_DIR}
[[ $(uname -r) = 5.4.214-htree1 ]] || exit 2
base=/sys/module/ext4/parameters
restore() { echo 0 > "$base/htree_profile"; echo 8 > "$base/htree_linear_limit"; echo 0 > "$base/htree_search"; }
trap restore EXIT
restore
bash "$root/scripts/mount_images.sh" "$root"
python3 "$root/scripts/wait_idle.py" > "$root/results/settle-confirmation.log"
python3 "$root/scripts/capture_environment.py" > "$root/results/environment-confirmation.json"
for n in 1000 100000; do
  queries=$n
  (( queries > 10000 )) && queries=10000
  conditions=()
  for mode in binary binary_shadow linear hybrid8; do
    conditions+=(--condition "$mode=$root/fixtures/indexed/n$n")
  done
  HTREE_PROFILE=0 python3 "$root/scripts/bench_lookup.py" \
    --bench "$root/bench/lookup_bench" "${conditions[@]}" --files "$n" \
    --positive "$queries" --negative "$queries" --rounds 20 --seed 20261119 \
    --modes warmdir --drop-caches 2 --cpu 0 \
    --before-hook "$root/scripts/bench_before.sh" --after-hook "$root/scripts/bench_after.sh" \
    --output "$root/results/confirm-n$n"
done
restore
sync
umount "$root/fixtures/indexed"
umount "$root/fixtures/linear"
