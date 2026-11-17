#!/usr/bin/env python3
"""Check ext4 lookup policies across directory mutations in a private fixture.

Only a newly created check-mut-UUID directory under --root is modified. Existing
files are never reused or deleted. htree_search and htree_linear_limit are restored
in a finally block. Failure retains the fixture and a failure-report.json.
"""
import argparse
from collections import Counter
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import time
import traceback
import uuid


POLICIES = [("binary", 0, 8), ("linear", 1, 8),
            ("hybrid4", 2, 4), ("hybrid8", 2, 8), ("hybrid16", 2, 16)]
# Linux FS_IOC_GETFLAGS for the x86_64 VM. If unavailable, report unknown;
# actual index layout must then be checked separately.
FS_IOC_GETFLAGS = 0x80086601
EXT4_INDEX_FL = 0x1000


def interrupted(signum, frame):
    raise InterruptedError("received signal %d" % signum)


def flags_for(fd):
    try:
        import array
        buf = array.array("l", [0])
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, buf, True)
        flags = int(buf[0])
        return {"flags_hex": hex(flags), "index_flag": bool(flags & EXT4_INDEX_FL)}
    except (OSError, ValueError) as exc:
        return {"flags_hex": None, "index_flag": None, "error": str(exc)}


def create_file(fd, name, data):
    out = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=fd)
    try:
        view = memoryview(data)
        while view:
            written = os.write(out, view)
            if not written:
                raise OSError("zero-length write")
            view = view[written:]
        st = os.fstat(out)
        return {"dev": st.st_dev, "ino": st.st_ino, "data": data}
    finally:
        os.close(out)


def check_absent(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        if exc.errno == errno.ENOENT:
            return
        raise
    raise AssertionError("expected ENOENT for %s" % name)


def verify_tree(fds, expected, stage, drop_caches, absent=()):
    if drop_caches:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text(str(drop_caches) + "\n")
    links = Counter((x["dev"], x["ino"]) for items in expected.values() for x in items.values())
    digest = hashlib.sha256()
    identities = hashlib.sha256()
    count = 0
    start = time.monotonic_ns()
    for dirname in sorted(fds):
        fd = fds[dirname]
        names = sorted(os.listdir(fd))
        if names != sorted(expected[dirname]):
            raise AssertionError("%s: directory names differ at %s" % (dirname, stage))
        for name in names:
            want = expected[dirname][name]
            got = os.stat(name, dir_fd=fd, follow_symlinks=False)  # fstatat
            if not stat.S_ISREG(got.st_mode):
                raise AssertionError("non-regular entry: %s/%s" % (dirname, name))
            if (got.st_dev, got.st_ino) != (want["dev"], want["ino"]):
                raise AssertionError("wrong inode returned: %s/%s at %s" % (dirname, name, stage))
            if got.st_nlink != links[(got.st_dev, got.st_ino)]:
                raise AssertionError("wrong link count: %s/%s" % (dirname, name))
            if got.st_size != len(want["data"]):
                raise AssertionError("wrong file size: %s/%s" % (dirname, name))
            opened = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            try:
                fst = os.fstat(opened)
                data = os.read(opened, len(want["data"]) + 1)
            finally:
                os.close(opened)
            if (fst.st_dev, fst.st_ino) != (want["dev"], want["ino"]) or data != want["data"]:
                raise AssertionError("wrong open/content: %s/%s" % (dirname, name))
            # This hash ignores inode allocation, so it can match after recreation.
            key = (dirname + "/" + name).encode()
            digest.update(len(key).to_bytes(4, "little") + key)
            digest.update(len(data).to_bytes(4, "little") + data)
            digest.update(got.st_nlink.to_bytes(4, "little"))
            identities.update(key + (":%d:%d" % (got.st_dev, got.st_ino)).encode())
            count += 1
        for i in range(16):
            check_absent(fd, "absent_%s_%02d" % (stage, i))
    for dirname, name in absent:
        check_absent(fds[dirname], name)
    return {"stage": stage, "files": count,
            "directory_counts": {k: len(v) for k, v in expected.items()},
            "content_name_nlink_sha256": digest.hexdigest(),
            "identity_sha256": identities.hexdigest(),
            "negative_checks": len(fds) * 16 + len(absent),
            "verification_elapsed_ns": time.monotonic_ns() - start,
            "drop_caches": drop_caches}


def run_mode(fds, expected, label, drop_caches, baseline_hash, stages):
    a, b = fds["src"], fds["dst"]
    def verify(step, absent=()):
        result = verify_tree(fds, expected, label + "_" + step, drop_caches, absent)
        stages.append(result)
        return result
    verify("before")
    # 1. Same-directory rename must preserve inode identity.
    os.rename("file_00000000", "renamed_00000000", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["renamed_00000000"] = expected["src"].pop("file_00000000")
    verify("rename", [("src", "file_00000000")])
    # 2. Link, then remove the original; the remaining name must stay valid.
    os.link("file_00000001", "hardlink_00000001", src_dir_fd=a, dst_dir_fd=a, follow_symlinks=False)
    expected["src"]["hardlink_00000001"] = expected["src"]["file_00000001"]
    verify("hardlink")
    os.unlink("file_00000001", dir_fd=a)
    expected["src"].pop("file_00000001")
    verify("unlink_original", [("src", "file_00000001")])
    # 3. Move to another indexed directory and check both namespaces.
    os.rename("file_00000002", "cross_00000002", src_dir_fd=a, dst_dir_fd=b)
    expected["dst"]["cross_00000002"] = expected["src"].pop("file_00000002")
    verify("cross_rename", [("src", "file_00000002")])
    # 4. Replace an existing destination. Retain its old inode via a hardlink
    # so the fixture can be restored without hiding a wrong-inode result.
    os.link("file_00000003", "saved_00000003", src_dir_fd=b, dst_dir_fd=b, follow_symlinks=False)
    expected["dst"]["saved_00000003"] = expected["dst"]["file_00000003"]
    os.rename("file_00000003", "file_00000003", src_dir_fd=a, dst_dir_fd=b)
    expected["dst"]["file_00000003"] = expected["src"].pop("file_00000003")
    verify("replace_rename", [("src", "file_00000003")])
    # 5. Cache a missing name after unlink; recreation must invalidate it.
    old_data = expected["src"]["file_00000004"]["data"]
    os.unlink("file_00000004", dir_fd=a)
    expected["src"].pop("file_00000004")
    verify("unlink", [("src", "file_00000004")])
    expected["src"]["file_00000004"] = create_file(a, "file_00000004", b"recreated:" + old_data)
    verify("recreate")
    # Restore names, content and link counts for a comparable next policy.
    os.rename("renamed_00000000", "file_00000000", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["file_00000000"] = expected["src"].pop("renamed_00000000")
    os.rename("hardlink_00000001", "file_00000001", src_dir_fd=a, dst_dir_fd=a)
    expected["src"]["file_00000001"] = expected["src"].pop("hardlink_00000001")
    os.rename("cross_00000002", "file_00000002", src_dir_fd=b, dst_dir_fd=a)
    expected["src"]["file_00000002"] = expected["dst"].pop("cross_00000002")
    os.rename("file_00000003", "file_00000003", src_dir_fd=b, dst_dir_fd=a)
    expected["src"]["file_00000003"] = expected["dst"].pop("file_00000003")
    os.rename("saved_00000003", "file_00000003", src_dir_fd=b, dst_dir_fd=b)
    expected["dst"]["file_00000003"] = expected["dst"].pop("saved_00000003")
    os.unlink("file_00000004", dir_fd=a)
    expected["src"]["file_00000004"] = create_file(a, "file_00000004", old_data)
    final = verify("restored", [("src", "renamed_00000000"), ("src", "hardlink_00000001"),
                                 ("dst", "cross_00000002"), ("dst", "saved_00000003")])
    if final["content_name_nlink_sha256"] != baseline_hash:
        raise AssertionError("restored content/name/link digest differs from baseline")
    return stages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="mounted isolated test filesystem directory")
    parser.add_argument("--sysfs", type=Path, default=Path("/sys/module/ext4/parameters"))
    parser.add_argument("--files", type=int, default=1200, help="files per src/dst directory; minimum 1001")
    parser.add_argument("--drop-caches", type=int, choices=[0, 2, 3], default=0)
    parser.add_argument("--require-index", action="store_true", help="fail unless both directories have EXT4_INDEX_FL")
    parser.add_argument("--output", type=Path, help="optional new JSON report path; default stdout only")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir() or args.files < 1001:
        parser.error("root must be a directory and --files must be >= 1001")
    if args.output and args.output.exists():
        parser.error("output already exists")
    parameters = {name: args.sysfs / name for name in ("htree_search", "htree_linear_limit")}
    originals = {name: path.read_text().strip() for name, path in parameters.items()}
    for value in originals.values():
        int(value)  # Fail before changing anything if the interface is unexpected.
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    fixture = root / ("check-mut-" + uuid.uuid4().hex)
    fixture.mkdir(mode=0o700)
    fixture_identity = (fixture.stat().st_dev, fixture.stat().st_ino)
    fds = {}
    expected = {"src": {}, "dst": {}}
    report = {"schema": 1, "fixture": str(fixture), "files_per_directory": args.files,
              "initial_parameters": originals, "drop_caches": args.drop_caches,
              "result": "FAIL", "modes": [], "restoration_errors": [],
              "note": "Correctness only; verification_elapsed_ns is not a performance benchmark."}
    success = False
    try:
        for dirname in expected:
            directory = fixture / dirname
            directory.mkdir(mode=0o700)
            fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
            fds[dirname] = fd
            for i in range(args.files):
                name = "file_%08d" % i
                data = ("%s payload %08d\n" % (dirname, i)).encode()
                expected[dirname][name] = create_file(fd, name, data)
        report["directory_flags"] = {name: flags_for(fd) for name, fd in fds.items()}
        if args.require_index and not all(x["index_flag"] is True for x in report["directory_flags"].values()):
            raise AssertionError("both directories must have EXT4_INDEX_FL")
        baseline = verify_tree(fds, expected, "initial", args.drop_caches)
        report["baseline"] = baseline
        for label, mode, limit in POLICIES:
            parameters["htree_linear_limit"].write_text(str(limit) + "\n")
            parameters["htree_search"].write_text(str(mode) + "\n")
            observed = {name: path.read_text().strip() for name, path in parameters.items()}
            if observed != {"htree_search": str(mode), "htree_linear_limit": str(limit)}:
                raise AssertionError("policy readback mismatch: %r" % observed)
            entry = {"label": label, "mode": mode, "limit": limit, "parameters": observed, "stages": []}
            report["modes"].append(entry)
            run_mode(fds, expected, label, args.drop_caches,
                     baseline["content_name_nlink_sha256"], entry["stages"])
            entry["result"] = "PASS"
        success = True
    except BaseException as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
    finally:
        # Try restoring BOTH parameters even if the first restoration fails.
        for name in ("htree_linear_limit", "htree_search"):
            try:
                parameters[name].write_text(originals[name] + "\n")
                if parameters[name].read_text().strip() != originals[name]:
                    raise OSError("restoration readback mismatch")
            except BaseException as exc:
                report["restoration_errors"].append("%s: %s" % (name, exc))
                success = False
        for fd in fds.values():
            os.close(fd)
    if success:
        try:
            st = fixture.lstat()
            if not stat.S_ISDIR(st.st_mode) or (st.st_dev, st.st_ino) != fixture_identity:
                raise AssertionError("private fixture identity changed; refusing cleanup")
            shutil.rmtree(str(fixture))
            report["result"] = "PASS"
            report["fixture_retained"] = False
        except BaseException as exc:
            report["cleanup_error"] = "%s: %s" % (type(exc).__name__, exc)
            success = False
    if not success:
        report["fixture_retained"] = True
        if fixture.is_dir():
            (fixture / "failure-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("FAIL: retained private fixture at %s" % fixture, file=sys.stderr)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as out:
            out.write(text)
    sys.stdout.write(text)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
