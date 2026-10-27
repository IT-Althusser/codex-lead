param([Parameter(Mandatory=$true)][string]$TmpRoot)
$ErrorActionPreference = 'Stop'
$work = Join-Path $TmpRoot ([Guid]::NewGuid().ToString('N'))
$fakeApp = Join-Path $work 'app'
New-Item -ItemType Directory -Path $fakeApp -Force | Out-Null
$fakeExe = Join-Path $fakeApp 'ChatGPT.exe'
New-Item -ItemType File -Path $fakeExe | Out-Null
$launcher = Join-Path $PSScriptRoot 'launch_desktop.ps1'
$global:CodexLeadLauncherTest = [pscustomobject]@{Calls=@(); BackendFails=$false; Running=@(); ProbeFailures=0}

# 测试替身不会连接网络、启动或关闭真实桌面进程。
function FakePython {
    $mode = if ($args -contains 'backend') { 'backend' } else { 'doctor' }
    $global:CodexLeadLauncherTest.Calls += $mode
    if (($mode -eq 'backend' -and $global:CodexLeadLauncherTest.BackendFails) -or
        ($mode -eq 'doctor' -and $global:CodexLeadLauncherTest.ProbeFailures -gt 0)) {
        if ($mode -eq 'doctor') { $global:CodexLeadLauncherTest.ProbeFailures-- }
        $global:LASTEXITCODE = 1
        return '{"ready":false}'
    }
    $global:LASTEXITCODE = 0
    return '{"ready":true}'
}
function Get-AppxPackage { return [pscustomobject]@{InstallLocation=$work} }
function Get-Process { return $global:CodexLeadLauncherTest.Running }
function Start-Process {
    param($FilePath, [switch]$PassThru)
    if ($FilePath -ne $fakeExe) { throw 'Unexpected executable' }
    $global:CodexLeadLauncherTest.Calls += 'start'
    return [pscustomobject]@{Id=123}
}
function Assert-True($condition, $message) {
    if (-not $condition) { throw "Assertion failed: $message" }
}
function Reset-Case {
    $global:CodexLeadLauncherTest.Calls = @()
    $global:CodexLeadLauncherTest.BackendFails = $false
    $global:CodexLeadLauncherTest.Running = @()
    $global:CodexLeadLauncherTest.ProbeFailures = 0
}
function Expect-Failure([scriptblock]$action, [string]$pattern) {
    $matched = $false
    try { & $action | Out-Null } catch {
        if ($_.Exception.Message -notmatch $pattern) { throw }
        $matched = $true
    }
    Assert-True $matched "expected failure matching $pattern"
}
$oldUrl = $env:CODEX_APP_SERVER_WS_URL
$oldForce = $env:CODEX_APP_SERVER_FORCE_CLI
try {
    $env:CODEX_APP_SERVER_WS_URL = 'test-old-url'
    $env:CODEX_APP_SERVER_FORCE_CLI = 'test-old-force'
    Reset-Case
    & $launcher -Python FakePython | Out-Null
    Assert-True (($global:CodexLeadLauncherTest.Calls -join ',') -eq 'backend,start,doctor') 'backend checked before start, real-connection check after start'
    Assert-True ($env:CODEX_APP_SERVER_WS_URL -eq 'test-old-url') 'URL environment restored'
    Assert-True ($env:CODEX_APP_SERVER_FORCE_CLI -eq 'test-old-force') 'force environment restored'

    Reset-Case
    $global:CodexLeadLauncherTest.BackendFails = $true
    Expect-Failure { & $launcher -Python FakePython -Restart } 'Backend is not ready'
    Assert-True (($global:CodexLeadLauncherTest.Calls -join ',') -eq 'backend') 'backend failure cannot close or start desktop'

    Reset-Case
    $global:CodexLeadLauncherTest.Running = @([pscustomobject]@{Path=$fakeExe; MainWindowHandle=1})
    Expect-Failure { & $launcher -Python FakePython } 'Confirm saved work'
    Assert-True (-not ($global:CodexLeadLauncherTest.Calls -contains 'start')) 'running desktop needs restart authorization'

    Reset-Case
    $global:CodexLeadLauncherTest.Running = @([pscustomobject]@{Path=$fakeExe; MainWindowHandle=0})
    Expect-Failure { & $launcher -Python FakePython -Restart } 'tray menu'
    Assert-True (-not ($global:CodexLeadLauncherTest.Calls -contains 'start')) 'tray-hidden desktop cannot be duplicated'

    Reset-Case
    $global:CodexLeadLauncherTest.ProbeFailures = 1
    & $launcher -Python FakePython | Out-Null
    Assert-True (($global:CodexLeadLauncherTest.Calls -join ',') -eq 'backend,start,doctor,doctor') 'connection startup race is waited, no duplicate launch'

    Reset-Case
    $global:CodexLeadLauncherTest.ProbeFailures = 100
    Expect-Failure { & $launcher -Python FakePython -ConnectTimeout 1 } 'connection was not verified'
    Assert-True (@($global:CodexLeadLauncherTest.Calls | Where-Object {$_ -eq 'start'}).Count -eq 1) 'timeout cannot launch another desktop'
    Assert-True ($env:CODEX_APP_SERVER_WS_URL -eq 'test-old-url') 'timeout restores environment'
    Write-Output 'PowerShell launcher regression: 6 cases passed; no real processes were started or closed.'
} finally {
    if ($null -eq $oldUrl) { Remove-Item Env:CODEX_APP_SERVER_WS_URL -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_WS_URL = $oldUrl }
    if ($null -eq $oldForce) { Remove-Item Env:CODEX_APP_SERVER_FORCE_CLI -ErrorAction SilentlyContinue } else { $env:CODEX_APP_SERVER_FORCE_CLI = $oldForce }
    Remove-Item -LiteralPath $work -Recurse -Force
    Remove-Variable -Name CodexLeadLauncherTest -Scope Global
}
