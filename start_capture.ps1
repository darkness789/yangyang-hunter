param(
    [ValidateSet('proxy', 'local')][string]$Mode = 'proxy',
    [string]$ProcessName = 'WeChatAppEx',
    [string]$UpstreamProxy = 'http://127.0.0.1:12000',
    [int]$ListenPort = 8080,
    [int]$DurationSeconds = 180,
    [switch]$SeedProbe
)

$ErrorActionPreference = 'Stop'
$mitmdump = 'C:\Program Files\mitmproxy\bin\mitmdump.exe'
if (-not (Test-Path -LiteralPath $mitmdump)) {
    throw "mitmdump not found: $mitmdump"
}

$env:YLGY_CAPTURE_DIR = Join-Path $PSScriptRoot 'captures'
$addon = Join-Path $PSScriptRoot 'capture_map.py'

if ($Mode -eq 'local') {
    Write-Host "Capturing $ProcessName traffic to $env:YLGY_CAPTURE_DIR"
    & $mitmdump --mode "local:$ProcessName" -s $addon --set flow_detail=0
    exit $LASTEXITCODE
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WinInetProxyRefresh {
    [DllImport("wininet.dll", SetLastError = true)]
    public static extern bool InternetSetOption(IntPtr handle, int option, IntPtr buffer, int length);
    public static void Refresh() {
        InternetSetOption(IntPtr.Zero, 39, IntPtr.Zero, 0);
        InternetSetOption(IntPtr.Zero, 37, IntPtr.Zero, 0);
    }
}
'@

$settings = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$old = Get-ItemProperty -Path $settings
$oldEnabled = [int]$old.ProxyEnable
$oldServer = [string]$old.ProxyServer
$stateFile = Join-Path $PSScriptRoot 'captures\proxy_state.json'
if (Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $ListenPort is already in use"
}

$captureProcess = $null
try {
    New-Item -ItemType Directory -Path $env:YLGY_CAPTURE_DIR -Force | Out-Null
    [pscustomobject]@{ ProxyEnable = $oldEnabled; ProxyServer = $oldServer } |
        ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Set-ItemProperty -Path $settings -Name ProxyServer -Value "127.0.0.1:$ListenPort"
    Set-ItemProperty -Path $settings -Name ProxyEnable -Value 1
    [WinInetProxyRefresh]::Refresh()
    Write-Host "Capturing for $DurationSeconds seconds via 127.0.0.1:$ListenPort; upstream $UpstreamProxy"
    Write-Host "Output: $env:YLGY_CAPTURE_DIR"
    Write-Host 'Open or restart 羊了个羊：星球, then enter a level.'
    $stdout = Join-Path $PSScriptRoot 'captures\mitmdump.stdout.log'
    $stderr = Join-Path $PSScriptRoot 'captures\mitmdump.stderr.log'
    $arguments = @('--mode', "upstream:$UpstreamProxy", '--listen-host', '127.0.0.1', '--listen-port', "$ListenPort", '-s', $addon, '--set', 'flow_detail=0')
    if ($SeedProbe) { $arguments += @('-s', (Join-Path $PSScriptRoot 'seed_probe.py')) }
    $captureProcess = Start-Process -FilePath $mitmdump -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $pidFile = Join-Path $PSScriptRoot 'captures\mitmdump.pid'
    Set-Content -LiteralPath $pidFile -Value $captureProcess.Id
    Wait-Process -Id $captureProcess.Id -Timeout $DurationSeconds -ErrorAction SilentlyContinue
} finally {
    if ($captureProcess -and -not $captureProcess.HasExited) {
        Stop-Process -Id $captureProcess.Id -ErrorAction SilentlyContinue
    }
    Set-ItemProperty -Path $settings -Name ProxyServer -Value $oldServer
    Set-ItemProperty -Path $settings -Name ProxyEnable -Value $oldEnabled
    [WinInetProxyRefresh]::Refresh()
    Remove-Item -LiteralPath (Join-Path $PSScriptRoot 'captures\mitmdump.pid') -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stateFile -ErrorAction SilentlyContinue
    Write-Host 'Previous Windows proxy settings restored.'
}
