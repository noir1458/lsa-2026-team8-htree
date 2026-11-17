#!/usr/bin/env python3
"""Balanced lookup trials with explicit cache preparation and counter hooks.

Runs one C process for all queries in each trial. Does not create/mount images.
Cache dropping is opt-in and requires privileges. Hook scripts receive:
PID trial_id label cache_mode output_prefix. Before hook runs after setup/warmup;
after hook runs after the measured queries and before output-file operations.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import random
import select
import subprocess
import time


def wait_byte(fd, process, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], min(0.25, max(0, end - time.monotonic())))
        if ready:
            if os.read(fd, 1) == b"R":
                return
            raise RuntimeError("benchmark handshake pipe closed early")
        if process.poll() is not None:
            raise RuntimeError("benchmark exited before handshake: %s" % process.returncode)
    raise TimeoutError("benchmark handshake timed out")


def run_one(args, condition, mode, rep, trial_id, seed):
    prefix = args.output / ("trial_%04d_%s_%s" % (trial_id, condition["label"], mode))
    # Cache preparation is deliberately outside the measured process. drop=2
    # does not guarantee all inode/dentry objects can be evicted.
    if args.drop_caches:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text(str(args.drop_caches) + "\n")
    ready_r, ready_w = os.pipe()
    start_r, start_w = os.pipe()
    done_r, done_w = os.pipe()
    release_r, release_w = os.pipe()
    cmd = [str(args.bench), "--dir", condition["directory"], "--files", str(args.files),
           "--positive", str(args.positive), "--negative", str(args.negative),
           "--seed", str(seed), "--trial", str(trial_id), "--label", condition["label"],
           "--latencies", str(prefix) + ".latencies.csv", "--ready-fd", str(ready_w),
           "--start-fd", str(start_r), "--done-fd", str(done_w), "--release-fd", str(release_r)]
    if mode in ("warmdir", "warm"):
        cmd.append("--warm-dir")
    if mode == "warm":
        cmd += ["--warmup", "1"]
    if args.cpu is not None:
        cmd = ["taskset", "-c", str(args.cpu)] + cmd
    record = {"trial": trial_id, "round": rep, "condition": condition, "cache_mode": mode,
              "query_seed": seed, "drop_caches": args.drop_caches, "command": cmd,
              "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    parent_fds = [ready_r, start_w, done_r, release_w]
    child_fds = [ready_w, start_r, done_w, release_r]
    process = None
    with open(str(prefix) + ".csv", "x") as out, open(str(prefix) + ".stderr", "x") as err:
        try:
            process = subprocess.Popen(cmd, stdout=out, stderr=err, pass_fds=child_fds)
            for fd in child_fds:
                os.close(fd)
            child_fds = []
            wait_byte(ready_r, process, args.timeout)
            hook_args = [str(process.pid), str(trial_id), condition["label"], mode, str(prefix)]
            if args.before_hook:
                subprocess.run([str(args.before_hook)] + hook_args, check=True, timeout=args.timeout)
            os.write(start_w, b"G")
            wait_byte(done_r, process, args.timeout)
            if args.after_hook:
                subprocess.run([str(args.after_hook)] + hook_args, check=True, timeout=args.timeout)
            os.write(release_w, b"G")
            rc = process.wait(timeout=args.timeout)
            record["returncode"] = rc
            if rc:
                raise RuntimeError("benchmark failed (%s); see %s.stderr" % (rc, prefix))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            for fd in parent_fds + child_fds:
                os.close(fd)
            Path(str(prefix) + ".json").write_text(json.dumps(record, indent=2) + "\n")
    with open(str(prefix) + ".csv") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1 or int(rows[0]["errors"]) != 0:
        raise RuntimeError("unexpected result rows or correctness failure")
    rows[0].update(cache_mode=mode, round=rep, drop_caches=args.drop_caches)
    return rows[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--condition", action="append", required=True, help="LABEL=/absolute/dir")
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--positive", type=int)
    parser.add_argument("--negative", type=int)
    parser.add_argument("--modes", default="warmdir,warm", help="comma-separated: none,warmdir,warm")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--drop-caches", type=int, choices=[0, 2, 3], default=0)
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--before-hook", type=Path)
    parser.add_argument("--after-hook", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.bench = args.bench.resolve()
    args.output = args.output.resolve()
    if args.positive is None:
        args.positive = args.files
    if args.negative is None:
        args.negative = args.files
    if args.files <= 0 or not 0 <= args.positive <= args.files or args.negative < 0:
        parser.error("invalid file/query counts")
    if not args.positive + args.negative or args.rounds <= 0:
        parser.error("empty workload")
    conditions = []
    for value in args.condition:
        label, sep, directory = value.partition("=")
        if not sep or not label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in label):
            parser.error("conditions require safe LABEL=/directory")
        path = Path(directory).resolve()
        if not path.is_dir():
            parser.error("condition directory does not exist: %s" % path)
        conditions.append({"label": label, "directory": str(path)})
    if len({c["label"] for c in conditions}) != len(conditions):
        parser.error("condition labels must be unique")
    modes = args.modes.split(",")
    if any(m not in ("none", "warmdir", "warm") for m in modes) or len(set(modes)) != len(modes):
        parser.error("invalid or repeated modes")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be new or empty")
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    metadata.update(uname=list(platform.uname()), conditions=conditions,
                    loadavg=list(os.getloadavg()), cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None)
    for p in ("/proc/uptime", "/proc/meminfo", "/proc/version"):
        if Path(p).exists():
            metadata[p] = Path(p).read_text()
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rng = random.Random(args.seed)
    cells = [(c, m) for c in conditions for m in modes]
    # Each round contains every cell exactly once. Alternate a shuffled order
    # with its reversal to balance early/late positions across round pairs.
    rows = []
    for rep in range(args.rounds):
        if rep % 2 == 0:
            rng.shuffle(cells)
            order = list(cells)
        else:
            order = list(reversed(order))
        seed = (args.seed + rep * 1000003) % (2**64)
        for condition, mode in order:
            trial = len(rows)
            row = run_one(args, condition, mode, rep, trial, seed)
            rows.append(row)
            print(json.dumps({"trial": trial, "round": rep, "label": condition["label"],
                              "cache": mode, "elapsed_ns": row["elapsed_ns"], "p95_ns": row["p95_ns"]}), flush=True)
            with (args.output / "summary.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)


if __name__ == "__main__":
    main()
