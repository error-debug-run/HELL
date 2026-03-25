param(
    [string]$ExePath = "gui\bin\Release\net10.0\gui.exe",
    [string]$PfxPath = "hell-cert.pfx",
    [string]$Password = "your_password"
)

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
    $PfxPath, $Password
)

Set-AuthenticodeSignature `
    -FilePath $ExePath `
    -Certificate $cert `
    -TimestampServer "http://timestamp.digicert.com"

Write-Host "Signed: $ExePath"