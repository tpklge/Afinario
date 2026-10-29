"""Fetch pinned build inputs and assemble an explicit, secret-free resource tree."""

import hashlib
import importlib.metadata
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
STAGE = ROOT / "build" / "windows-resources"


def download(url: str, destination: Path, checksum: str | None = None):
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        print(f"Downloading {destination.name}", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        temporary.replace(destination)
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum and digest != checksum:
        raise RuntimeError(f"SHA-256 mismatch: {destination.name}")
    return digest


def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows installer on Windows x64.")
    manifest = json.loads((Path(__file__).parent / "downloads.json").read_text(encoding="utf-8"))
    for item in manifest:
        archive = TOOLS / item["file"]
        download(item["url"], archive, item["sha256"])
        if item["name"] == "inno":
            continue
        extracted = TOOLS / "packaging" / item["name"]
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                if not (extracted / member.filename).resolve().is_relative_to(extracted.resolve()):
                    raise RuntimeError("Unsafe archive member")
            source.extractall(extracted)
    target_tools = STAGE / "tools"
    target_tools.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe", "fpcalc.exe"):
        matches = list((TOOLS / "packaging").rglob(name))
        if len(matches) != 1:
            raise RuntimeError(f"Missing or ambiguous input: {name}")
        shutil.copyfile(matches[0], target_tools / name)
    notices = STAGE / "notices"
    notices.mkdir(parents=True, exist_ok=True)
    ffmpeg = TOOLS / "packaging" / "ffmpeg" / "ffmpeg-9.0.2-essentials_build"
    for name in ("LICENSE", "README.txt"):
        target = notices / "ffmpeg" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ffmpeg / name, target)
    for name, url in {
        "chromaprint-LICENSE.md": "https://raw.githubusercontent.com/acoustid/chromaprint/v1.6.2/LICENSE.md",
    }.items():
        download(url, notices / name)
    lgpl = TOOLS / "LGPL-2.1.txt"
    download(
        "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n9.0.2/COPYING.LGPLv2.1",
        lgpl,
        "246041b6ecf9bc32d718a62c57877c78b5eb397b6467e74ed7ae2626ab189c30",
    )
    shutil.copyfile(lgpl, notices / "LGPL-2.1.txt")
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
                    target = notices / "python-packages" / name / Path(*safe_parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", notices / "Python-LICENSE.txt")
    (notices / "packages.json").write_text(
        json.dumps(packages, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (notices / "downloads.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copyfile(ROOT / "packaging" / "windows" / "THIRD-PARTY.txt", notices / "README.txt")
    print(f"Resources ready: {STAGE}", flush=True)


if __name__ == "__main__":
    main()
