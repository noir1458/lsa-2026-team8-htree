#!/usr/bin/env python3
"""Create deterministic empty regular files on a caller-provided test filesystem.

No formatting, mounting, or cache changes. Existing nonempty target directories
are rejected so creating fixtures never silently reuses a different layout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--counts", default="100,1000,10000")
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--order", choices=["random", "sequential"], default="random")
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    counts = [int(s) for s in args.counts.split(",")]
    if not counts or any(n <= 0 for n in counts) or len(set(counts)) != len(counts):
        parser.error("counts must be distinct positive integers")
    if not args.parent.is_dir():
        parser.error("--parent must already exist on the intended mounted filesystem")
    if args.metadata.exists():
        parser.error("metadata output already exists")
    targets = [args.parent / ("n%d" % n) for n in counts]
    if any(p.exists() and (not p.is_dir() or any(p.iterdir())) for p in targets):
        parser.error("a target is nonempty; use fresh fixture directories")
    rows = []
    for count, directory in zip(counts, targets):
        directory.mkdir(exist_ok=True)
        ids = list(range(count))
        if args.order == "random":
            random.Random(args.seed + count).shuffle(ids)
        digest = hashlib.sha256()
        begin = time.monotonic_ns()
        for i in ids:
            name = "file_%08d" % i
            fd = os.open(str(directory / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.close(fd)
            digest.update((name + "\n").encode())
        st = directory.stat()
        rows.append({"directory": str(directory.resolve()), "files": count,
                     "creation_order_sha256": digest.hexdigest(),
                     "creation_elapsed_ns": time.monotonic_ns() - begin,
                     "st_dev": st.st_dev, "st_ino": st.st_ino,
                     "st_size": st.st_size, "st_blocks": st.st_blocks,
                     "file_bytes": 0})
    os.sync() if hasattr(os, "sync") else None
    metadata = {"schema": 1, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "uname": list(platform.uname()), "seed": args.seed,
                "creation_order": args.order, "fixtures": rows,
                "note": "Filesystem features and inode INDEX flags must be verified separately."}
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    with args.metadata.open("x") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
