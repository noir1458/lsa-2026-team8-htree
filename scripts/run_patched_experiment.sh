#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: run_patched_experiment.sh EXPERIMENT_DIR}
[[ $(uname -r) = 5.4.214-htree1 ]] || { echo 'Unexpected kernel' >&2; exit 2; }
base=/sys/module/ext4/parameters
original_mode=$(cat "$base/htree_search")
original_limit=$(cat "$base/htree_linear_limit")
restore_policy() {
  echo 0 > "$base/htree_profile"
  echo "$original_limit" > "$base/htree_linear_limit"
  echo "$original_mode" > "$base/htree_search"
}
trap restore_policy EXIT
bash "$root/scripts/mount_images.sh" "$root"
dmesg > "$root/results/dmesg-before.txt"
printf 'phase=mutation-correctness\n'
python3 "$root/scripts/check_mutations.py" --root "$root/fixtures/indexed" \
  --files 1200 --drop-caches 2 --require-index --output "$root/results/mutation-check.json" \
  > "$root/results/mutation-check.stdout.json"
printf 'phase=settle\n'
python3 "$root/scripts/wait_idle.py" > "$root/results/settle-patched.log"
python3 "$root/scripts/capture_environment.py" > "$root/results/environment-patched.json"
printf 'phase=policy-timing\n'
bash "$root/scripts/run_suite.sh" "$root" patched 10 > "$root/results/run-patched.log" 2>&1
printf 'phase=index-control\n'
bash "$root/scripts/run_index_control.sh" "$root" > "$root/results/run-index-control.log" 2>&1
printf 'phase=profile\n'
bash "$root/scripts/run_profile.sh" "$root" > "$root/results/run-profile.log" 2>&1
restore_policy
printf 'phase=micro\n'
python3 "$root/scripts/wait_idle.py" > "$root/results/settle-micro.log"
python3 "$root/scripts/capture_environment.py" > "$root/results/environment-micro.json"
taskset -c 0 "$root/bench/dx_search_bench" 2000000 10 > "$root/results/micro.csv" 2> "$root/results/micro-check.txt"
dmesg > "$root/results/dmesg-after.txt"
printf 'phase=filesystem-check\n'
sync
for kind in indexed linear; do
  umount "$root/fixtures/$kind"
  e2fsck -fn "$root/fixtures/$kind.img" > "$root/results/fsck-$kind.txt" 2>&1
done
printf 'phase=complete\n'
