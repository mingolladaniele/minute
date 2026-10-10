# Build dist\minute\minute.exe (PyInstaller) and dist\minute-setup-<version>.exe (Inno Setup).
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

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
& $iscc /Qp packaging\minute.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

Get-ChildItem dist\minute-setup-*.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
