#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: run_suite.sh EXPERIMENT_DIR stock-or-patched [rounds]}
phase=${2:?}
rounds=${3:-10}
[[ $phase = stock || $phase = patched ]] || exit 2
if [[ $phase = patched ]]; then
  [[ -e /sys/module/ext4/parameters/htree_search ]] || { echo 'Experimental kernel required' >&2; exit 2; }
else
  [[ ! -e /sys/module/ext4/parameters/htree_search ]] || { echo 'Unmodified baseline kernel required' >&2; exit 2; }
fi
for n in 100 1000 10000 100000; do
  queries=$n
  (( queries > 10000 )) && queries=10000
  dir="$root/fixtures/indexed/n$n"
  conditions=(--condition "stock=$dir")
  if [[ $phase = patched ]]; then
    conditions=()
    for mode in binary linear hybrid4 hybrid8 hybrid16; do
      conditions+=(--condition "$mode=$dir")
    done
  fi
  HTREE_PROFILE=0 python3 "$root/scripts/bench_lookup.py" \
    --bench "$root/bench/lookup_bench" "${conditions[@]}" --files "$n" \
    --positive "$queries" --negative "$queries" --rounds "$rounds" \
    --modes warmdir,warm --drop-caches 2 --cpu 0 \
    --before-hook "$root/scripts/bench_before.sh" --after-hook "$root/scripts/bench_after.sh" \
    --output "$root/results/$phase-n$n"
done
