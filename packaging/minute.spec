# PyInstaller spec: a windowed, one-folder build in dist/minute/.
# Build with scripts/build.ps1 (it fetches the transcribe.cpp engine first).
from pathlib import Path

ROOT = Path(SPECPATH).parent
ENGINE = "vendor/transcribe-native-windows-x86_64-cpu-vulkan"

a = Analysis(
    [str(ROOT / "minute.pyw")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "minute" / "ui"), "minute/ui"),
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
        (str(ROOT / "CHANGELOG.md"), "."),
        (str(ROOT / ENGINE), ENGINE),
    ],
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "pystray._win32"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="minute",
    icon=str(ROOT / "assets" / "icon.ico"),
    console=False,
    version=str(ROOT / "packaging" / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="minute")
