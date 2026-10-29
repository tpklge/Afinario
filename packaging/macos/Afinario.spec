"""Apple Silicon app with shared frozen desktop/worker modules and audio tools."""
import importlib.metadata
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parents[1]
stage = root / "build" / "macos-resources"
datas = [(str(stage / "notices"), "notices")]
binaries = [(str(stage / "tools" / name), "tools") for name in ("ffmpeg", "ffprobe", "fpcalc")]
hiddenimports = ["keyring.backends.macOS", "afinario.shazam_worker"]
for package in ("shazamio", "shazamio_core"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for package in ("afinario", "PySide6-Essentials", "PySide6-Addons", "httpx", "platformdirs", "mutagen"):
    datas += copy_metadata(package)
for package in ("keyring", "shazamio"):
    datas += copy_metadata(package, recursive=True)
a = Analysis(
    [str(root / "packaging" / "windows" / "entry.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
desktop = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Afinario",
              console=False, debug=False, strip=False, upx=False, target_arch="arm64")
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AfinarioWorker",
             console=True, debug=False, strip=False, upx=False, target_arch="arm64")
coll = COLLECT(desktop, worker, a.binaries, a.datas, strip=False, upx=False, name="Afinario")
app = BUNDLE(
    coll, name="Afinario.app", icon=str(stage / "Afinario.icns"),
    bundle_identifier="br.com.tpklge.afinario",
    version=importlib.metadata.version("afinario"),
    info_plist={
        "CFBundleDisplayName": "Afinário",
        "CFBundleShortVersionString": importlib.metadata.version("afinario"),
        "LSMinimumSystemVersion": "15.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Afinário — componentes de terceiros em Contents/Resources/notices",
    },
)
