"""Verify relocation, macOS floor, signatures and offline frozen execution."""

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from macholib import mach_o
from macholib.MachO import MachO

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
MAGIC = {b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def visible_files(app):
    # Preserve content/signatures; Finder-hidden source flags are not app resources.
    for entry in [app, *app.rglob("*")]:
        if entry.is_symlink():
            continue
        flags = entry.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(entry, flags & ~stat.UF_HIDDEN)
    for name in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
        subprocess.run(
            ["/usr/bin/xattr", "-dr", name, str(app)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def audit(app):
    binaries = []
    for entry in app.rglob("*"):
        if entry.is_symlink() or not entry.is_file():
            continue
        if entry.name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")) or entry.name in {
            ".env",
            "afinario.local.toml",
            "credentials.json",
            "secrets.json",
        }:
            raise RuntimeError(f"Private data in bundle: {entry.relative_to(app)}")
        with entry.open("rb") as stream:
            magic = stream.read(4)
        if magic not in MAGIC:
            continue
        minimums = []
        for header in MachO(str(entry)).headers:
            # CPU_TYPE_ARM64 = CPU_TYPE_ARM | CPU_ARCH_ABI64.
            if header.header.cputype != 0x0100000C:
                raise RuntimeError(f"Non-arm64 code in bundle: {entry.relative_to(app)}")
            for command, data, _ in header.commands:
                if command.cmd == mach_o.LC_BUILD_VERSION and data.platform == 1:
                    minimums.append(data.minos)
                elif command.cmd == mach_o.LC_VERSION_MIN_MACOSX:
                    minimums.append(data.version)
        if not minimums or max(minimums) > (15 << 16):
            raise RuntimeError(f"macOS >15 required by: {entry.relative_to(app)} ({minimums})")
        links = subprocess.check_output(["/usr/bin/otool", "-L", str(entry)], text=True)
        external = [
            line.strip().split(" (", 1)[0]
            for line in links.splitlines()[1:]
            if line.strip().startswith("/")
            and not line.strip().startswith(("/System/Library/", "/usr/lib/"))
        ]
        if external:
            raise RuntimeError(f"External dependency in {entry.relative_to(app)}: {external}")
        binaries.append(str(entry.relative_to(app)))
    return binaries


def check(app):
    app = Path(app).resolve()
    REPORTS.mkdir(exist_ok=True)
    visible_files(app)
    binaries = audit(app)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "QT_", "DYLD_", "AFINARIO_ACOUSTID", "AFINARIO_AUDD"))
    }
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    target = REPORTS / "macos-bundle-check.json"
    with tempfile.TemporaryDirectory(prefix="Afinario installed 日本語 ") as directory:
        with (REPORTS / "macos-bundle-check.log").open("w") as log:
            result = subprocess.run(
                [str(app / "Contents/MacOS/Afinario"), "--self-test", str(target)],
                cwd=directory,
                env=environment,
                stdout=log,
                stderr=log,
                timeout=180,
            )
    if result.returncode or not target.is_file():
        raise RuntimeError("Frozen app check failed; see reports/macos-bundle-check.log")
    report = json.loads(target.read_text())
    if not report.get("ok"):
        raise RuntimeError("Frozen app check failed; see reports/macos-bundle-check.json")
    report["mach_o_files_checked"] = len(binaries)
    report["external_libraries"] = []
    report["minimum_macos"] = "15.0"
    report["architecture"] = "arm64"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Bundle OK: {len(binaries)} arm64 binaries, no external libraries, GUI/audio check passed",
        flush=True,
    )
    return report


if __name__ == "__main__":
    import sys

    check(sys.argv[1])
