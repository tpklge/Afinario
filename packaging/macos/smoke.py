"""Exercise the actual installer payload and mounted DMG without touching /Applications."""

import importlib.metadata
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from validate import REPORTS, check

ROOT = Path(__file__).resolve().parents[2]


def run(*command):
    subprocess.run([str(item) for item in command], check=True)


def main():
    version = importlib.metadata.version("afinario")
    name = f"Afinario-{version}-macos-arm64"
    artifacts = ROOT / "dist/installers"
    with tempfile.TemporaryDirectory(prefix="Afinario install test 日本語 ") as directory:
        work = Path(directory)
        expanded = work / "expanded"
        run("/usr/sbin/pkgutil", "--expand-full", artifacts / f"{name}.pkg", expanded)
        apps = list(expanded.rglob("Afinario.app"))
        if len(apps) != 1:
            raise RuntimeError("Unexpected installer payload")
        package_report = check(apps[0])
        (REPORTS / "macos-pkg-check.json").write_text(
            json.dumps(package_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        mount = work / "mounted"
        mount.mkdir()
        run(
            "/usr/bin/hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            mount,
            artifacts / f"{name}.dmg",
        )
        try:
            if not (mount / "Applications").is_symlink():
                raise RuntimeError("Missing Applications shortcut")
            installed = work / "Applications" / "Afinario.app"
            installed.parent.mkdir()
            run("/usr/bin/ditto", mount / "Afinario.app", installed)
        finally:
            run("/usr/bin/hdiutil", "detach", mount)
        image_report = check(installed)
        (REPORTS / "macos-dmg-check.json").write_text(
            json.dumps(image_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.copyfile(expanded / "Distribution", REPORTS / "macos-installer-distribution.xml")
    print("PKG payload and installed DMG app checks passed; real user data untouched.")


if __name__ == "__main__":
    main()
