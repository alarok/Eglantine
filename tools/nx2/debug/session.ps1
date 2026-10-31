# Summarize one emulator log: stream errors, frame times, lag, and settings.
# Usage: session.ps1 <eden_log.txt>
param([Parameter(Mandatory = $true)][string]$Log)
$open = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'eden-cli.exe' }
if ($open) { "emulator open: $($open.ProcessId -join ', ')" } else { "emulator closed" }
$last = Get-Content $Log -Tail 1
"last line: " + $last.Substring(0, [Math]::Min(70, $last.Length))
foreach ($q in 'Unimplemented engine', 'QMD failed', 'method out of range', 'Dropping method', 'Special puller', 'Dropped', 'REWRITE', 'Unmapped Device', 'shader rejected') {
    "$q : $((Select-String -Path $Log -Pattern $q).Count)"
}
"--- frames"
Select-String -Path $Log -Pattern 'last 600 presents' | Select-Object -Last 8 | ForEach-Object {
    $line = $_.Line
    $at = $line.Substring(0, 13)
    $i = $line.IndexOf('presents: ')
    $text = $line.Substring($i + 10)
    "$at $($text.Substring(0, [Math]::Min(150, $text.Length)))"
}
"--- GPU memory"
Select-String -Path $Log -Pattern 'VMA heap 0' | Select-Object -Last 1 | ForEach-Object { $_.Line.Substring($_.Line.IndexOf('VMA heap')) }
