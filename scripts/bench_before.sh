#!/usr/bin/env bash
set -euo pipefail
label=$3
base=/sys/module/ext4/parameters
[[ -e $base/htree_search ]] || exit 0
echo 0 > "$base/htree_profile"
case "$label" in
  binary|stock) echo 0 > "$base/htree_search" ;;
  linear) echo 1 > "$base/htree_search" ;;
  hybrid4|hybrid8|hybrid16)
    echo "${label#hybrid}" > "$base/htree_linear_limit"
    echo 2 > "$base/htree_search" ;;
  *) echo "Unknown policy $label" >&2; exit 2 ;;
esac
echo 1 > "$base/htree_reset"
echo "${HTREE_PROFILE:-0}" > "$base/htree_profile"
