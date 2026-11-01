# Measure whether the emulator is CPU bound: total CPU seconds per wall second, and the threads
# that pull more than 5 % of one core in the window. It does not start the emulator.
# Usage: thread_cpu.ps1 [-ProcessName eden-cli] [-Delay 0] [-Window 70]
# The thread ids are anonymous: use rip_sampler.py or stack_sampler.py to name one by its work.
param(
    [string]$ProcessName = 'eden-cli',
    [int]$Delay = 0,
    [int]$Window = 70
)
Start-Sleep -Seconds $Delay
$p = Get-Process $ProcessName -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { "no process named $ProcessName"; exit 1 }
$cores = [Environment]::ProcessorCount
$last = @{}
$acc = @{}
foreach ($t in $p.Threads) { $last["$($t.Id)"] = $t.TotalProcessorTime.TotalSeconds }
$cpu0 = $p.TotalProcessorTime.TotalSeconds
$end = (Get-Date).AddSeconds($Window)
while ((Get-Date) -lt $end) {
    foreach ($t in $p.Threads) {
        $k = "$($t.Id)"
        $v = $t.TotalProcessorTime.TotalSeconds
        if ($last.ContainsKey($k)) {
            if (-not $acc.ContainsKey($k)) { $acc[$k] = 0.0 }
            $acc[$k] += [double]($v - $last[$k])
        }
        $last[$k] = $v
    }
    Start-Sleep -Milliseconds 500
}
$p.Refresh()
$cpu1 = $p.TotalProcessorTime.TotalSeconds
"logical cores: $cores"
"process CPU: {0:N1} % of one core, {1:N2} cores busy" -f (($cpu1 - $cpu0) / $Window * 100), (($cpu1 - $cpu0) / $Window)
"threads above 5 % of one core:"
$acc.GetEnumerator() | Sort-Object Value -Descending |
    Where-Object { ($_.Value / $Window * 100) -gt 5 } |
    ForEach-Object { "  tid {0}  {1:N1} %" -f $_.Key, ($_.Value / $Window * 100) }
