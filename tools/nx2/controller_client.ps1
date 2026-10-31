param(
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [ValidateRange(0, 65535)][int]$Port = 0,
    [string]$Command = '{"op":"status"}',
    [ValidateRange(0, 5500)][int]$KeepAliveMs = 0,
    [switch]$DisconnectAfterReply
)

$ErrorActionPreference = 'Stop'
if ($Port -eq 0) {
    $ports = @(Get-NetTCPConnection -State Listen -OwningProcess $ProcessId -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
        Select-Object -ExpandProperty LocalPort -Unique)
    if ($ports.Count -ne 1) {
        throw 'Expected one loopback listener for this process. Supply -Port from the startup log.'
    }
    $Port = $ports[0]
}
$connection = [System.Net.Sockets.TcpClient]::new()
$reader = $null
$writer = $null
try {
    $connect = $connection.ConnectAsync('127.0.0.1', $Port)
    if (-not $connect.Wait(2000)) { throw 'Controller API connection timed out' }
    $stream = $connection.GetStream()
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.IO.StreamWriter]::new($stream, $encoding, 1024, $true)
    $reader = [System.IO.StreamReader]::new($stream, $encoding, $false, 1024, $true)
    $writer.AutoFlush = $true
    $writer.WriteLine('{"op":"status"}')
    $handshake = $reader.ReadLineAsync()
    if (-not $handshake.Wait(3000)) { throw 'Controller API identity check timed out' }
    if ($null -eq $handshake.Result) { throw 'Controller API closed before its identity response' }
    $identity = $handshake.Result | ConvertFrom-Json
    if (-not $identity.ok -or $identity.api -cne 'eglantine-controller-api-v1' -or
        $identity.pid -ne $ProcessId -or $identity.port -ne $Port) {
        throw 'Controller API identity or process ID does not match. No input was sent.'
    }
    $writer.WriteLine($Command)
    $read = $reader.ReadLineAsync()
    if (-not $read.Wait(3000)) { throw 'Controller API did not respond within three seconds' }
    $reply = $read.Result
    if ($null -eq $reply) { throw 'Controller API closed without a response' }
    Write-Output $reply
    $response = $reply | ConvertFrom-Json
    if (-not $response.ok) { exit 1 }
    if (-not $DisconnectAfterReply) {
        if ($KeepAliveMs -eq 0 -and $null -ne $response.duration_ms) {
            $KeepAliveMs = [Math]::Max(1, [Math]::Min(5000, [int]$response.duration_ms)) + 25
        }
        if ($KeepAliveMs -gt 0) { Start-Sleep -Milliseconds $KeepAliveMs }
    }
} finally {
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $writer) { $writer.Dispose() }
    $connection.Dispose()
}
