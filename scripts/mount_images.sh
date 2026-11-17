#!/usr/bin/env bash
set -euo pipefail
root=${1:?usage: mount_images.sh /absolute/experiment-directory}
[[ $root = /* ]] || exit 2
for kind in indexed linear; do
  img="$root/fixtures/$kind.img"
  target="$root/fixtures/$kind"
  [[ -f $img && -d $target ]] || exit 2
  if mountpoint -q "$target"; then
    device=$(findmnt -n -o SOURCE --mountpoint "$target")
    backing=$(losetup -n -O BACK-FILE "$device")
    [[ $backing = "$img" ]] || { echo 'Unexpected mount at fixture path' >&2; exit 2; }
  else
    mount -o loop,noatime "$img" "$target"
  fi
done
