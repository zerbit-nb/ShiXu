param([Parameter(Mandatory=$true)][string]$QQDirectory,
      [Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
try {
    $source = (Resolve-Path -LiteralPath $QQDirectory).Path
    $link = [IO.Path]::GetFullPath($Destination)
    if ([IO.Path]::GetFileName($link) -notmatch '^qq-client-[0-9a-f]{16}$') { throw 'Invalid mapping name' }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'QQ.exe') -PathType Leaf)) { throw 'Missing client' }
    if (Test-Path -LiteralPath $link) { throw 'Mapping already exists' }
    # Creates only a junction inside Shixu's managed folder. No QQ files change.
    New-Item -ItemType Junction -Path $link -Value $source -ErrorAction Stop | Out-Null
    exit 0
} catch {
    [Console]::Error.WriteLine('QQ mapping could not be prepared.')
    exit 1
}
