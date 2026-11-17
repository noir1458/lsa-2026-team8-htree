#!/usr/bin/env bash
set -euo pipefail
base=/sys/module/ext4/parameters
prefix=$5
[[ -e $base/htree_search ]] || exit 0
echo 0 > "$base/htree_profile"
cat "$base/htree_stats" > "$prefix.stats"
printf 'search=%s limit=%s profile_during_trial=%s\n' \
  "$(cat "$base/htree_search")" "$(cat "$base/htree_linear_limit")" \
  "${HTREE_PROFILE:-0}" > "$prefix.policy"
