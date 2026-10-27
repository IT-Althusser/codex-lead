param(
    [string]$Url = 'ws://127.0.0.1:18765',
    [string]$Python = 'python',
    [ValidateRange(1, 120)][int]$ConnectTimeout = 30,
    [switch]$Restart
)
$ErrorActionPreference = 'Stop'
if ($Url -notmatch '^ws://127\.0\.0\.1:\d+/?$') { throw 'Only loopback WebSocket URLs are allowed' }
$bridge = Join-Path $PSScriptRoot 'desktop.py'
if (-not (Test-Path -LiteralPath $bridge)) { throw 'desktop.py is missing' }
# 先验证依赖和后端协议，不能先关闭桌面再发现后端不可用。
$backend = & $Python -X utf8 -I -B $bridge backend --url $Url 2>&1
if ($LASTEXITCODE -ne 0) { throw "Backend is not ready; desktop was not closed. $backend" }
$package = Get-AppxPackage OpenAI.Codex | Select-Object -First 1
if (-not $package) { throw 'Codex desktop package not found' }
$exe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Desktop executable not found: $exe" }
# 包含托盘隐藏的进程；关闭窗口不等于退出应用。
$running = @(Get-Process | Where-Object { $_.Path -eq $exe })
if ($running.Count -gt 0 -and -not $Restart) { throw 'Desktop is running. Confirm saved work before using -Restart.' }
$roots = @($running | Where-Object { $_.MainWindowHandle -ne 0 })
if ($running.Count -gt 0 -and $roots.Count -eq 0) { throw 'Desktop is hidden or has no main window. Exit from the tray menu; no force termination was attempted.' }
foreach ($process in $roots) {
    if (-not $process.CloseMainWindow()) { throw 'Desktop declined normal close. Exit from the tray menu; no force termination was attempted.' }
    if (-not $process.WaitForExit(15000)) { throw 'Desktop is still running. Exit from the tray menu; no force termination was attempted.' }
}
if (@(Get-Process | Where-Object { $_.Path -eq $exe }).Count -gt 0) { throw 'Desktop processes remain. Do not launch another instance; exit fully first.' }
$oldUrl = $env:CODEX_APP_SERVER_WS_URL
$oldForce = $env:CODEX_APP_SERVER_FORCE_CLI
try {
    $env:CODEX_APP_SERVER_WS_URL = $Url
    Remove-Item Env:CODEX_APP_SERVER_FORCE_CLI -ErrorAction SilentlyContinue
    $started = Start-Process -FilePath $exe -PassThru
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    do {
        $probe = & $Python -X utf8 -I -B $bridge doctor --url $Url 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Output "Desktop connected: PID=$($started.Id), Endpoint=$Url"
            Write-Output $probe
            return
        }
        [System.Threading.Thread]::Sleep(500)
    } while ($timer.Elapsed.TotalSeconds -lt $ConnectTimeout)
    throw "Desktop was launched but its shared connection was not verified. Do not launch another instance. $probe"
} finally {
    if ($null -eq $oldUrl) { Remove-Item Env:CODEX_APP_SERVER_WS_URL -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_WS_URL = $oldUrl }
    if ($null -eq $oldForce) { Remove-Item Env:CODEX_APP_SERVER_FORCE_CLI -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_FORCE_CLI = $oldForce }
}
