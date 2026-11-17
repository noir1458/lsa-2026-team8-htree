#!/usr/bin/env bash
set -euo pipefail
# Use a fresh Linux 5.4.214 source tree, never a coursework/shared tree.
source_dir=${1:?usage: build_kernel.sh FRESH_LINUX_5.4.214_SOURCE}
project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ -f $source_dir/fs/ext4/namei.c && -f $source_dir/Makefile ]] || exit 2
cd "$source_dir"
[[ $(make -s kernelversion) = 5.4.214 ]] || { echo 'Linux 5.4.214 required' >&2; exit 2; }
patch --dry-run -p1 < "$project_dir/patches/0001-ext4-htree-search-experiment.patch"
patch -p1 < "$project_dir/patches/0001-ext4-htree-search-experiment.patch"
cp "$project_dir/results/config-5.4.214-b0" .config
scripts/config --set-str LOCALVERSION -htree1
scripts/config --disable LOCALVERSION_AUTO
make olddefconfig
make -j"$(nproc)" bzImage modules
echo 'Build complete. Install only on the intended test VM:'
echo 'sudo make modules_install && sudo make install'
echo 'Use a one-time GRUB entry; keep the usual boot default.'
