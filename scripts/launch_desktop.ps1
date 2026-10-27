param(
    [string]$Url = 'ws://127.0.0.1:18765',
    [switch]$Restart
)
$ErrorActionPreference = 'Stop'
if ($Url -notmatch '^ws://127\.0\.0\.1:\d+/?$') { throw 'Only loopback WebSocket URLs are allowed' }
$package = Get-AppxPackage OpenAI.Codex | Select-Object -First 1
if (-not $package) { throw 'Codex desktop package not found' }
$exe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Desktop executable not found: $exe" }
# Include tray-hidden processes; closing a window is not proof of exiting.
$running = @(Get-Process | Where-Object { $_.Path -eq $exe })
if ($running.Count -gt 0 -and -not $Restart) { throw 'Desktop is running. Confirm saved work before using -Restart.' }
$roots = @($running | Where-Object { $_.MainWindowHandle -ne 0 })
if ($running.Count -gt 0 -and $roots.Count -eq 0) { throw 'Desktop is hidden or has no main window. Ask the user to exit from the tray menu; no force termination was attempted.' }
foreach ($process in $roots) {
    if (-not $process.CloseMainWindow()) { throw 'Desktop declined normal close; ask the user to exit. No force termination was attempted.' }
    if (-not $process.WaitForExit(15000)) { throw 'Desktop is still running. Ask the user to exit from the tray menu; no force termination was attempted.' }
}
if (@(Get-Process | Where-Object { $_.Path -eq $exe }).Count -gt 0) { throw 'Desktop processes remain. Do not launch another instance; ask the user to exit fully.' }
$uri = [Uri]$Url
$tcp = New-Object System.Net.Sockets.TcpClient
try { $tcp.Connect($uri.Host, $uri.Port) } finally { $tcp.Dispose() }
$oldUrl = $env:CODEX_APP_SERVER_WS_URL
$oldForce = $env:CODEX_APP_SERVER_FORCE_CLI
try {
    $env:CODEX_APP_SERVER_WS_URL = $Url
    Remove-Item Env:CODEX_APP_SERVER_FORCE_CLI -ErrorAction SilentlyContinue
    $started = Start-Process -FilePath $exe -PassThru
    Write-Output "Desktop launched: PID=$($started.Id), Endpoint=$Url. Run desktop.py doctor to verify the actual connection."
} finally {
    if ($null -eq $oldUrl) { Remove-Item Env:CODEX_APP_SERVER_WS_URL -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_WS_URL = $oldUrl }
    if ($null -eq $oldForce) { Remove-Item Env:CODEX_APP_SERVER_FORCE_CLI -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_FORCE_CLI = $oldForce }
}
