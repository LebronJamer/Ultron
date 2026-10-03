# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Ultron (onedir build, wrapped by Inno Setup)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH).resolve()          # .../UltronV1/scripts
ROOT = SPEC_DIR.parent                       # .../UltronV1
APP = ROOT / "app"
MODELS = APP / "models"

datas = []
binaries = []
hiddenimports = []

# Packages with native libs / dynamic plugins that need full collection.
for pkg in (
    "vosk",
    "sounddevice",
    "pycaw",
    "pystray",
    "keyboard",
    "pygetwindow",
    "screen_brightness_control",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "win32com",
    "win32com.client",
    "pythoncom",
    "win32api",
    "win32gui",
    "win32clipboard",
    "win32con",
    "win32timezone",
    "comtypes",
    "comtypes.stream",
    "wmi",
    "pystray._win32",
    "pygetwindow._pygetwindow_win",
    "keyboard._winkeyboard",
]

# Bundle the offline speech model when present (downloaded pre-build).
for model_dir in MODELS.glob("vosk-model-*"):
    datas.append((str(model_dir), f"models/{model_dir.name}"))

# App assets (icons, banners).
datas.append((str(APP / "assets"), "assets"))

a = Analysis(
    [str(ROOT / "launch.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ultron",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP / "assets" / "icons" / "icon.ico"),
    version=str(SPEC_DIR / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Ultron",
)
