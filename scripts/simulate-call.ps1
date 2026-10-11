# Simulate a call on your own, to try minute without anybody else.
#   powershell -ExecutionPolicy Bypass -File scripts\simulate-call.ps1 [-Seconds 180] [-Audio path\to\conversation.mp3]
#
# A fake "Zoom" (a renamed copy of ffmpeg) holds the microphone for -Seconds, so minute's call
# detection sees a call starting and ending. Meanwhile -Audio plays through the speakers and is
# recorded as THEM; talk into your mic as YOU. Without -Audio, Handy's recordings are used.
# Needs ffmpeg + ffplay on PATH. Wear headphones so the mic doesn't hear the speakers.
param(
    [int]$Seconds = 180,
    [string]$Audio = ""
)
$ErrorActionPreference = "Stop"

function Invoke-Native([string]$exe, [string[]]$arguments) {
    # ffmpeg talks on stderr; Windows PowerShell would treat that as a failure, so run it through cmd.
    $quoted = ($arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
    cmd /c "`"$exe`" $quoted 2>&1"
}

$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
$ffplay = (Get-Command ffplay -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg -or -not $ffplay) { throw "ffmpeg and ffplay are needed: winget install Gyan.FFmpeg" }

$work = Join-Path $env:TEMP "minute-simulated-call"
New-Item -ItemType Directory -Force $work | Out-Null

# The fake call app: ffmpeg under a call app's name, with its DLLs next to it.
$bin = Split-Path $ffmpeg
Copy-Item "$bin\*.dll" $work -Force -ErrorAction SilentlyContinue
Copy-Item $ffmpeg "$work\zoom.exe" -Force

# The other side of the call.
if (-not $Audio) {
    $recordings = Get-ChildItem "$env:APPDATA\com.pais.handy\recordings\*.wav" -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 6
    if (-not $recordings) { throw "No -Audio given and no Handy recordings found: pass -Audio with a recording of people talking" }
    $list = Join-Path $work "list.txt"
    $recordings | ForEach-Object { "file '$($_.FullName -replace "'", "'\''")'" } | Set-Content -Encoding ascii $list
    $Audio = Join-Path $work "them.wav"
    Invoke-Native $ffmpeg @("-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", $list, "-ar", "16000", "-ac", "1", $Audio) | Out-Null
}

$mic = (Invoke-Native $ffmpeg @("-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy") | Select-String '"(.+)" \(audio\)' | Select-Object -First 1).Matches.Groups[1].Value
if (-not $mic) { throw "No microphone found" }

Write-Host ""
Write-Host "Simulated call for $Seconds s (microphone: $mic)."
Write-Host "- minute should start on its own: notification + pill on the right edge of the screen."
Write-Host "- Open minute from the tray, write a few notes, talk into your mic now and then."
Write-Host "- When the call ends the pill turns amber; minute stops about 45 s later."
Write-Host ""

$call = Start-Process -PassThru -WindowStyle Hidden "$work\zoom.exe" -ArgumentList @(
    "-hide_banner", "-loglevel", "error", "-f", "dshow", "-i", "audio=`"$mic`"", "-t", "$Seconds", "-f", "null", "-")
Start-Sleep 4  # let minute see the call and start recording before the others speak
$them = Start-Process -PassThru -WindowStyle Hidden $ffplay -ArgumentList @(
    "-nodisp", "-autoexit", "-loglevel", "quiet", "-t", "$($Seconds - 10)", "`"$Audio`"")

$call.WaitForExit()
if (-not $them.HasExited) { $them.Kill() }
Write-Host "Call over. minute stops in about 45 s, then writes the title and the enhanced notes."
