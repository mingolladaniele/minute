# Build dist\minute\minute.exe (PyInstaller) and dist\minute-setup-<version>.exe (Inno Setup).
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# The version comes from minute\__init__.py (__version__) and is stamped on both.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path minute\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) { throw "no __version__ in minute\__init__.py" }
$parts = ($version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable("040904B0", [
      StringStruct("CompanyName", "Daniele Mingolla"),
      StringStruct("FileDescription", "minute"),
      StringStruct("FileVersion", "$version"),
      StringStruct("InternalName", "minute"),
      StringStruct("OriginalFilename", "minute.exe"),
      StringStruct("ProductName", "minute"),
      StringStruct("ProductVersion", "$version"),
    ])]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])]),
  ],
)
"@ | Set-Content -Encoding utf8 packaging\version.txt
Write-Host "building minute $version"

if (-not (Test-Path "vendor\transcribe-native-windows-x86_64-cpu-vulkan\transcribe.dll")) {
    uv run python scripts/fetch_engine.py
}

uv sync
uv run pyinstaller packaging/minute.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup --scope user" }
& $iscc /Qp "/DAppVersion=$version" packaging\minute.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

Get-ChildItem "dist\minute-setup-$version.exe" | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
