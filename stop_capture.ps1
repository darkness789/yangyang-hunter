$settings = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$pidFile = Join-Path $PSScriptRoot 'captures\mitmdump.pid'
$stateFile = Join-Path $PSScriptRoot 'captures\proxy_state.json'
if (Test-Path -LiteralPath $pidFile) {
    $capturePid = [int](Get-Content -LiteralPath $pidFile -Raw)
    Stop-Process -Id $capturePid -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $stateFile)) {
    throw "Saved proxy settings not found: $stateFile"
}
$old = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
Set-ItemProperty -Path $settings -Name ProxyEnable -Value ([int]$old.ProxyEnable)
Set-ItemProperty -Path $settings -Name ProxyServer -Value ([string]$old.ProxyServer)
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class WinInetProxyRefresh { [DllImport("wininet.dll")] public static extern bool InternetSetOption(IntPtr handle,int option,IntPtr buffer,int length); }'
[WinInetProxyRefresh]::InternetSetOption([IntPtr]::Zero,39,[IntPtr]::Zero,0) | Out-Null
[WinInetProxyRefresh]::InternetSetOption([IntPtr]::Zero,37,[IntPtr]::Zero,0) | Out-Null
Remove-Item -LiteralPath $stateFile -ErrorAction SilentlyContinue
Write-Host 'Capture stopped and original Windows proxy settings restored.'
