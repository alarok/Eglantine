# Play one game with a scripted controller for a longer time.
# Usage: play.ps1 <eden-cli.exe> <label> <game> [seconds] [variant] -OutDir <dir> [-GamesFile <file>]
# <game> is a key of the games file: {"bananza": "<path to exefs main>", ...}.
# The games file defaults to games.local.json next to this script. Git ignores that file.
# A variant that needs a profile folder reads MATRIX_KEYS_FROM, MATRIX_REAL_PROFILE,
# MATRIX_FIRMWARE or MATRIX_NAND_FROM from the environment (see matrix.py).
param([string]$Exe, [string]$Label, [string]$Game, [int]$Seconds = 300, [string]$Variant = "base",
      [Parameter(Mandatory = $true)][string]$OutDir, [string]$GamesFile)
# A GUI with no game (for example a game list check) does not count as a heavy emulator.
$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(eglantine|eden|eden-cli|yuzu|cdb)(\.exe)?$' -and $_.CommandLine -match ' -g ' }
if ($p) { "BUSY: $($p | ForEach-Object { "$($_.ProcessId) $($_.Name)" })"; exit 1 }
if (-not $GamesFile) { $GamesFile = Join-Path $PSScriptRoot "games.local.json" }
if (-not (Test-Path -LiteralPath $GamesFile)) { "Games file not found: $GamesFile"; exit 2 }
$gamePath = (Get-Content -LiteralPath $GamesFile -Raw | ConvertFrom-Json).PSObject.Properties[$Game]
if (-not $gamePath -or -not $gamePath.Value) { "Game '$Game' is not in the games file: $GamesFile"; exit 2 }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
$tempDir = Join-Path $OutDir "tmp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$env:TEMP = $tempDir; $env:TMP = $tempDir
# SDL scancodes: A=4, left stick up=82, left stick down=81.
$events = New-Object System.Collections.Generic.List[string]
function Press([double]$At, [int]$Code, [double]$Hold = 0.3) { $events.Add("$($At.ToString([Globalization.CultureInfo]::InvariantCulture)):$Code"); $events.Add("$(($At + $Hold).ToString([Globalization.CultureInfo]::InvariantCulture)):-$Code") }
if ($Game -eq "pokopia") {
    Press 45 4; Press 50 82; Press 52 4
}
# Advance dialogues and menus, and walk forward for part of each cycle.
$start = if ($Game -eq "pokopia") { 58 } else { 30 }
if ($Variant -like "seed-play*") {
    # The owner's save: Continue on the title, then the hints, then the mine. Punch and walk.
    for ($t = 18; $t -lt 62; $t += 2) { Press $t 4 }
    for ($t = 62; $t -lt ($Seconds - 2); $t += 2) {
        Press $t 27
        if ($t % 8 -eq 0) { Press ($t + 1) 82 1.0 }
    }
} else {
for ($t = $start; $t -lt ($Seconds - 2); $t += 4) {
    Press $t 4
    if ($t % 16 -lt 4 -and $t -gt 120) { Press ($t + 1) 82 2.0 }
    # Y (scancode X=27) answers Bananza's "Punch" prompt.
    if ($Game -like "bananza*" -and $t -gt 90) { Press ($t + 2) 27 }
}
}
$script = "$OutDir\$Label-$Game.keys"
[IO.File]::WriteAllText($script, ($events -join ","))
$env:MATRIX_KEY_SCRIPT = "@$script"
$root = "$OutDir\$Label-$Game"
python -B "$PSScriptRoot\matrix.py" --root $root --exe $Exe --seconds $Seconds --game $gamePath.Value $Variant 2>&1 | Select-String -Pattern '"variant"' | ForEach-Object { $_.Line.Substring(0, [Math]::Min(240, $_.Line.Length)) }
$log = "$root\$Variant\user\log\eden_log.txt"
foreach ($pat in 'shader rejected', 'Draw skipped', 'Storage buffer index', 'PANIC', 'broke execution', 'not reached') { "$pat : $((Select-String -Path $log -Pattern $pat).Count)" }
Get-Content $log -Tail 2 | ForEach-Object { $_.Substring(0, [Math]::Min(170, $_.Length)) }
if (Get-ChildItem "$root\$Variant\frames" -Filter *.tga -ErrorAction SilentlyContinue) { python -B "$PSScriptRoot\thumbs.py" "$root\$Variant\frames" "$root\thumbs.png" 2>&1 | Select-Object -Last 1 }
