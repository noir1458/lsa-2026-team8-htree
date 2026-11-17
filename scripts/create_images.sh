#!/usr/bin/env bash
set -euo pipefail
# Only regular files inside a new experiment directory are formatted.
root=${1:?usage: create_images.sh /absolute/experiment-directory}
[[ $root = /* && -d $root ]] || exit 2
mkdir -p "$root/fixtures" "$root/results"
for kind in indexed linear; do
  img="$root/fixtures/$kind.img"
  [[ ! -e $img ]] || { echo "Refusing to replace $img" >&2; exit 2; }
done
for kind in indexed linear; do
  img="$root/fixtures/$kind.img"
  truncate -s 128M "$img"
  feature=dir_index
  [[ $kind = linear ]] && feature=^dir_index
  mkfs.ext4 -q -F -b 4096 -N 140000 -O "$feature" \
    -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=12345678-1234-1234-1234-123456789abc \
    "$img"
  mkdir -p "$root/fixtures/$kind"
  mount -o loop,noatime "$img" "$root/fixtures/$kind"
  counts=100,1000,10000
  [[ $kind = indexed ]] && counts=100,1000,10000,100000
  python3 "$root/scripts/setup_lookup_fixture.py" --parent "$root/fixtures/$kind" \
    --counts "$counts" --metadata "$root/results/fixture-$kind.json"
  dumpe2fs -h "$img" > "$root/results/filesystem-$kind.txt" 2>&1
  lsattr -d "$root/fixtures/$kind"/n* > "$root/results/flags-$kind.txt"
done
sync
