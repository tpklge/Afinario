"""Create a .pkg installer and a drag-to-Applications .dmg from a checked .app."""

import hashlib
import importlib.metadata
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from validate import check

ROOT = Path(__file__).resolve().parents[2]


def run(*command):
    subprocess.run([str(item) for item in command], check=True)


def create(app, work):
    check(app)
    payload = work / "payload"
    payload.mkdir()
    app = Path(shutil.move(str(app), payload / app.name))
    version = importlib.metadata.version("afinario")
    destination = ROOT / "dist/installers"
    destination.mkdir(parents=True, exist_ok=True)
    name = f"Afinario-{version}-macos-arm64"
    component = work / "component.plist"
    component.write_bytes(
        plistlib.dumps(
            [
                {
                    "RootRelativeBundlePath": "Afinario.app",
                    "BundleIsRelocatable": False,
                    "BundleIsVersionChecked": True,
                    "BundleHasStrictIdentifier": True,
                    "BundleOverwriteAction": "upgrade",
                }
            ]
        )
    )
    component_package = work / "Afinario-component.pkg"
    run(
        "/usr/bin/pkgbuild",
        "--root",
        payload,
        "--component-plist",
        component,
        "--install-location",
        "/Applications",
        "--identifier",
        "br.com.tpklge.afinario",
        "--version",
        version,
        component_package,
    )
    requirements = work / "requirements.plist"
    requirements.write_bytes(plistlib.dumps({"arch": ["arm64"], "os": ["15.0"]}))
    distribution = work / "Distribution.xml"
    run(
        "/usr/bin/productbuild",
        "--synthesize",
        "--product",
        requirements,
        "--package",
        component_package,
        distribution,
    )
    package = destination / f"{name}.pkg"
    run(
        "/usr/bin/productbuild",
        "--distribution",
        distribution,
        "--package-path",
        component_package.parent,
        package,
    )
    image_root = work / "dmg"
    if image_root.exists():
        shutil.rmtree(image_root)
    image_root.mkdir()
    run("/usr/bin/ditto", app, image_root / app.name)
    (image_root / "Applications").symlink_to("/Applications")
    shutil.copyfile(Path(__file__).with_name("LEIA-ME.txt"), image_root / "LEIA-ME.txt")
    image = destination / f"{name}.dmg"
    if image.exists():
        image.unlink()
    run(
        "/usr/bin/hdiutil",
        "create",
        "-volname",
        "Afinário",
        "-srcfolder",
        image_root,
        "-format",
        "UDZO",
        "-ov",
        image,
    )
    run("/usr/bin/hdiutil", "verify", image)
    artifacts = []
    for artifact in (package, image):
        with artifact.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{digest}  {artifact.name}\n", encoding="ascii"
        )
        artifacts.append(
            {"file": artifact.name, "sha256": digest, "bytes": artifact.stat().st_size}
        )
    report = {
        "version": version,
        "architecture": "arm64",
        "minimum_macos": "15.0",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_changes": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "python": sys.version.split()[0],
        "signing": "ad-hoc",
        "notarized": False,
        "artifacts": artifacts,
    }
    (destination / f"{name}-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main():
    # File-provider metadata in a synced checkout must not enter the installer.
    with tempfile.TemporaryDirectory(prefix="afinario-macos-release-") as directory:
        work = Path(directory)
        app = work / "Afinario.app"
        run("/usr/bin/ditto", ROOT / "build/macos/dist/Afinario.app", app)
        create(app, work)


if __name__ == "__main__":
    main()
