$certFile = Join-Path $env:USERPROFILE '.mitmproxy\mitmproxy-ca-cert.cer'
if (-not (Test-Path -LiteralPath $certFile)) {
    throw "Run mitmdump once to create the certificate: $certFile"
}
$thumbprint = (Get-PfxCertificate -FilePath $certFile).Thumbprint
if (Test-Path -LiteralPath "Cert:\CurrentUser\Root\$thumbprint") {
    Write-Host 'mitmproxy certificate is already trusted for this Windows user.'
} else {
    Import-Certificate -FilePath $certFile -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Write-Host 'mitmproxy certificate trusted for this Windows user.'
}
