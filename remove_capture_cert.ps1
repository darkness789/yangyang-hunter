$certFile = Join-Path $env:USERPROFILE '.mitmproxy\mitmproxy-ca-cert.cer'
if (-not (Test-Path -LiteralPath $certFile)) { throw "Certificate not found: $certFile" }
$thumbprint = (Get-PfxCertificate -FilePath $certFile).Thumbprint
$installed = Get-Item -LiteralPath "Cert:\CurrentUser\Root\$thumbprint" -ErrorAction SilentlyContinue
if ($installed) {
    Remove-Item -LiteralPath "Cert:\CurrentUser\Root\$thumbprint"
    Write-Host "Removed mitmproxy certificate $thumbprint from CurrentUser Root."
} else {
    Write-Host 'mitmproxy certificate is not installed in CurrentUser Root.'
}
