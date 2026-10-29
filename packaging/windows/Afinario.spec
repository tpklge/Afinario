# Build on Windows only: python -m PyInstaller packaging/windows/Afinario.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parents[1]
stage = root / "build" / "windows-resources"
datas = [(str(stage / "notices"), "notices")]
binaries = [(str(stage / "tools" / name), "tools") for name in (
    "ffmpeg.exe", "ffprobe.exe", "fpcalc.exe"
)]
hiddenimports = ["keyring.backends.Windows", "afinario.shazam_worker"]
for package in ("shazamio", "shazamio_core"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("afinario")
datas += copy_metadata("keyring", recursive=True)
datas += copy_metadata("shazamio", recursive=True)
datas += copy_metadata("PySide6-Essentials")
datas += copy_metadata("PySide6-Addons")
for package in ("httpx", "platformdirs", "mutagen"):
    datas += copy_metadata(package)
a = Analysis(
    [str(root / "packaging" / "windows" / "entry.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
desktop = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Afinario",
              console=False, debug=False, strip=False, upx=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AfinarioWorker",
             console=True, debug=False, strip=False, upx=False)
coll = COLLECT(desktop, worker, a.binaries, a.datas, strip=False, upx=False, name="Afinario")
