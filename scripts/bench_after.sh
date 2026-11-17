#!/usr/bin/env bash
set -euo pipefail
base=/sys/module/ext4/parameters
prefix=$5
if [[ ! -e $base/htree_search ]]; then
  [[ $3 = stock ]] && exit 0
  echo 'Patched policy requested but HTree controls are absent' >&2
  exit 2
fi
echo 0 > "$base/htree_profile"
cat "$base/htree_stats" > "$prefix.stats"
printf 'search=%s limit=%s profile_during_trial=%s\n' \
  "$(cat "$base/htree_search")" "$(cat "$base/htree_linear_limit")" \
  "${HTREE_PROFILE:-0}" > "$prefix.policy"
