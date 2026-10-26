param([Parameter(Mandatory=$true)][string]$QQPath)
$ErrorActionPreference = 'Stop'
try {
    $signature = Get-AuthenticodeSignature -LiteralPath $QQPath
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate.Subject.StartsWith('CN=Tencent Technology (Shenzhen) Company Limited,')) { exit 1 }
    exit 0
} catch { exit 1 }
