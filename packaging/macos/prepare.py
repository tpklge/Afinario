"""Build private macOS resources with no dependency on Homebrew at runtime."""

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / ".tools" / "macos-downloads"
STAGE = ROOT / "build" / "macos-resources"
TARGET = "15.0"


def fetch(item):
    destination = DOWNLOADS / item["file"]
    if not destination.exists():
        temporary = destination.with_suffix(".part")
        with urllib.request.urlopen(item["url"], timeout=60) as source, temporary.open("wb") as out:
            shutil.copyfileobj(source, out)
        temporary.replace(destination)
    with destination.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {destination.name}")
    extracted = DOWNLOADS / destination.name.removesuffix(".tar.gz")
    if not extracted.exists():
        extracted.mkdir()
        with tarfile.open(destination) as archive:
            archive.extractall(extracted, filter="data")
    return destination, extracted


def compile_ffmpeg(source, tools):
    # A source archive nested in our Git checkout must not inherit Afinário's tag.
    (source / "VERSION").write_text((source / "RELEASE").read_text())
    work = ROOT / "build" / "macos-ffmpeg"
    work.mkdir(parents=True, exist_ok=True)
    sdk = os.environ.get("SDKROOT")
    if not sdk:
        compatible_sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX15.sdk")
        sdk = (
            str(compatible_sdk)
            if compatible_sdk.exists()
            else subprocess.check_output(["/usr/bin/xcrun", "--show-sdk-path"], text=True).strip()
        )
    configure = [
        str(source / "configure"),
        "--disable-everything",
        "--disable-autodetect",
        "--disable-shared",
        "--enable-static",
        "--enable-small",
        "--disable-debug",
        "--disable-doc",
        "--disable-network",
        "--disable-avdevice",
        "--disable-swscale",
        "--enable-ffmpeg",
        "--enable-ffprobe",
        "--enable-protocol=file,pipe",
        "--enable-demuxer=mp3,mov,flac,ogg,matroska,wav,aiff,ape,asf,aac,caf,wv,ac3",
        "--enable-decoder=aac,aac_fixed,aac_latm,ac3,alac,ape,flac,mp3,mp3float,opus,vorbis,"
        "wavpack,wmav1,wmav2,wmapro,wmalossless,wmavoice,pcm*",
        "--enable-parser=aac,aac_latm,ac3,flac,mpegaudio,opus,vorbis",
        "--enable-encoder=pcm_s16le,pcm_s32le,flac",
        "--enable-muxer=wav,flac,streamhash,hash,null",
        "--enable-filter=aresample,aformat,anull",
        "--cc=/usr/bin/clang",
        "--host-cc=/usr/bin/clang",
        f"--host-cflags=-isysroot {sdk}",
        f"--host-ldflags=-isysroot {sdk}",
        f"--sysroot={sdk}",
        f"--extra-cflags=-mmacosx-version-min={TARGET}",
        f"--extra-ldflags=-mmacosx-version-min={TARGET}",
    ]
    signature = json.dumps(configure)
    stamp = work / "afinario-config.json"
    if not stamp.exists() or stamp.read_text() != signature:
        subprocess.run(configure, cwd=work, check=True, env={**os.environ, "SDKROOT": sdk})
        stamp.write_text(signature)
    subprocess.run(
        [
            "/bin/sh",
            str(source / "ffbuild/version.sh"),
            str(source),
            str(work / "libavutil/ffversion.h"),
        ],
        cwd=work,
        check=True,
    )
    subprocess.run(
        ["/usr/bin/make", f"-j{min(os.cpu_count() or 2, 8)}", "ffmpeg", "ffprobe"],
        cwd=work,
        check=True,
        env={**os.environ, "SDKROOT": sdk},
    )
    for name in ("ffmpeg", "ffprobe"):
        shutil.copyfile(work / name, tools / name)
        (tools / name).chmod(0o755)


def notices(inputs):
    target = STAGE / "notices"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    sources = target / "sources"
    sources.mkdir(exist_ok=True)
    for name in ("ffmpeg", "chromaprint-source"):
        archive, extracted = inputs[name]
        shutil.copyfile(archive, sources / archive.name)
        for original in extracted.rglob("*"):
            if original.is_file() and original.name.lower().startswith(("license", "copying")):
                destination = target / name / original.relative_to(extracted)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
    packages = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name.lower() in {"afinario", "pip", "uv", "ruff", "pytest", "pytest-qt"}:
            continue
        packages.append({"name": name, "version": distribution.version})
        for item in distribution.files or []:
            if any(word in str(item).lower() for word in ("license", "copying", "copyright")):
                original = Path(distribution.locate_file(item))
                if original.is_file():
                    safe_parts = [part for part in item.parts if part not in ("..", ".")]
                    destination = target / "python-packages" / name / Path(*safe_parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, destination)
    import sysconfig

    license_text = sysconfig.get_config_var("srcdir")
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "LICENSE.txt",
    ]
    if license_text:
        candidates.append(Path(license_text) / "LICENSE")
    for candidate in candidates:
        if candidate.is_file():
            shutil.copyfile(candidate, target / "Python-LICENSE.txt")
            break
    else:
        raise RuntimeError("Python LICENSE.txt not found; do not ship without the runtime license")
    (target / "packages.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("downloads.json"), target / "downloads.json")
    shutil.copyfile(Path(__file__).with_name("THIRD-PARTY.txt"), target / "README.txt")
    shutil.copyfile(Path(__file__).with_name("LEIA-ME.txt"), target / "LEIA-ME.txt")
    shutil.copyfile(Path(__file__), target / "ffmpeg-build-recipe.py")


def icon():
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    folder = STAGE / "Afinario.iconset"
    folder.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            dimension = size * scale
            image = QImage(dimension, dimension, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(dimension / 1024, dimension / 1024)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#151b24"))
            painter.drawRoundedRect(QRectF(16, 16, 992, 992), 210, 210)
            painter.setPen(
                QPen(
                    QColor("#76ddc7"),
                    66,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawLine(370, 260, 370, 500)
            painter.drawLine(650, 260, 650, 500)
            painter.drawArc(QRectF(370, 360, 280, 280), 180 * 16, 180 * 16)
            painter.drawLine(510, 640, 510, 800)
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            if not image.save(str(folder / f"icon_{size}x{size}{suffix}.png")):
                raise RuntimeError("Icon generation failed")
    subprocess.run(
        ["/usr/bin/iconutil", "-c", "icns", str(folder), "-o", str(STAGE / "Afinario.icns")],
        check=True,
    )


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("This recipe builds on Apple Silicon macOS only.")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    tools = STAGE / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(__file__).with_name("downloads.json").read_text())
    inputs = {item["name"]: fetch(item) for item in manifest}
    compile_ffmpeg(next(inputs["ffmpeg"][1].iterdir()), tools)
    fpcalc = next(inputs["fpcalc"][1].rglob("fpcalc"))
    shutil.copyfile(fpcalc, tools / "fpcalc")
    (tools / "fpcalc").chmod(0o755)
    notices(inputs)
    icon()
    print(f"Resources ready: {STAGE}", flush=True)


if __name__ == "__main__":
    main()
