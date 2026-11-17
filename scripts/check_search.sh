#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
check_dir="$(mktemp -d "${TMPDIR:-/tmp}/htree-search-check.XXXXXX")"
trap 'rm -rf "$check_dir"' EXIT
check_cc="${HTREE_TEST_CC:-cc}"

# The helpers must come from the committed patch, not a hand-copied model.
python3 - "$project_dir/patches/0001-ext4-htree-search-experiment.patch" \
    "$check_dir/htree_search_helpers.h" <<'PY'
from pathlib import Path
import sys
patch = Path(sys.argv[1]).read_text()
added = "\n".join(line[1:] for line in patch.splitlines()
                  if line.startswith("+") and not line.startswith("+++"))
start = added.index("/* entry 0 is the sentinel;")
end = added.index("/*\n * Profiling is a separate replay", start)
helpers = added[start:end]
assert "htree_binary_search(" in helpers
assert "htree_linear_search(" in helpers
Path(sys.argv[2]).write_text(helpers)
PY

printf 'environment='
uname -sm
printf 'compiler='
"$check_cc" --version | awk 'NR == 1 { print }'
printf '%s\n' 'sanitizers=address,undefined' \
    'scope=extracted kernel search helpers; not a kernel build or filesystem test'
"$check_cc" -O2 -g -Wall -Wextra -fsanitize=address,undefined \
    -I "$check_dir" "$project_dir/bench/check_search.c" \
    -o "$check_dir/check_search"
"$check_dir/check_search"
