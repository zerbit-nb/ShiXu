param([Parameter(Mandatory=$true)][string]$BootPath, [switch]$CheckOnly, [string]$QQPath, [switch]$RequireStopped)
$ErrorActionPreference = 'Stop'
try {
    $resolvedBoot = (Resolve-Path -LiteralPath $BootPath).Path
    $installFolder = [IO.Path]::GetDirectoryName($resolvedBoot)
    if ([IO.Path]::GetFileName($resolvedBoot) -ine 'NapCatWinBootMain.exe') { throw 'Invalid boot' }
    $externalQQ = $null
    if ($QQPath) {
        # Compare the exact recorded launch path without traversing its junction.
        # Installer RedirectionGuard blocks traversal; process/module checks below
        # still establish ownership before any process can be stopped.
        if (-not [IO.Path]::IsPathRooted($QQPath)) { throw 'Invalid QQ path' }
        $externalQQ = [IO.Path]::GetFullPath($QQPath)
        if ([IO.Path]::GetFileName($externalQQ) -ine 'QQ.exe') { throw 'Invalid QQ path' }
    }
    function Has-OwnedModule($row) {
        if (-not $externalQQ -or $row.ExecutablePath -ine $externalQQ) { return $false }
        try { $candidate = [Diagnostics.Process]::GetProcessById([int]$row.ProcessId) }
        catch [ArgumentException] { return $false }
        try {
            foreach ($module in $candidate.Modules) {
                if ($module.FileName.StartsWith($installFolder + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { return $true }
            }
            return $false
        } finally { $candidate.Dispose() }
    }
    $rows = @(Get-CimInstance Win32_Process)
    $roots = @($rows | Where-Object { $_.ExecutablePath -ieq $resolvedBoot })
    if ($roots.Count -gt 1) { throw 'Ambiguous installation' }
    $selected = [Collections.Generic.List[object]]::new()
    $selectedIds = [Collections.Generic.HashSet[int]]::new()
    foreach ($row in $roots) { $selected.Add($row); [void]$selectedIds.Add([int]$row.ProcessId) }
    # A loaded module under this installation identifies QQ children that outlive the loader.
    foreach ($row in $rows) {
        if (-not $selectedIds.Contains([int]$row.ProcessId) -and (Has-OwnedModule $row)) {
            $selected.Add($row); [void]$selectedIds.Add([int]$row.ProcessId)
        }
    }
    do {
        $children = @($rows | Where-Object { $selectedIds.Contains([int]$_.ParentProcessId) -and -not $selectedIds.Contains([int]$_.ProcessId) -and -not ($_.Name -ieq 'conhost.exe' -and $_.ExecutablePath -ieq (Join-Path $env:WINDIR 'System32\conhost.exe')) })
        foreach ($row in $children) {
            $internal = $row.ExecutablePath -and [IO.Path]::GetDirectoryName($row.ExecutablePath) -ieq $installFolder -and $row.Name -in @('QQ.exe','NapCatWinBootMain.exe')
            $external = $externalQQ -and $row.ExecutablePath -ieq $externalQQ
            if (-not ($internal -or $external)) { throw 'Untrusted descendant' }
            $selected.Add($row); [void]$selectedIds.Add([int]$row.ProcessId)
        }
    } while ($children.Count -gt 0)
    $owned = @($rows | Where-Object { $_.ExecutablePath -and [IO.Path]::GetDirectoryName($_.ExecutablePath) -ieq $installFolder -and $_.Name -in @('QQ.exe','NapCatWinBootMain.exe') })
    foreach ($row in $owned) { if (-not $selectedIds.Contains([int]$row.ProcessId)) { throw 'Orphan process' } }
    $handles = [Collections.Generic.List[object]]::new()
    foreach ($row in $selected) {
        try { $process = [Diagnostics.Process]::GetProcessById([int]$row.ProcessId) }
        catch [ArgumentException] { continue }
        [void]$process.Handle
        if ($process.MainModule.FileName -ine $row.ExecutablePath -or [Math]::Abs(($process.StartTime.ToUniversalTime() - $row.CreationDate.ToUniversalTime()).TotalSeconds) -gt 1) { throw 'Process identity changed' }
        $handles.Add($process)
    }
    if ($CheckOnly) {
        $active = $handles.Count -gt 0
        foreach ($process in $handles) { $process.Dispose() }
        if ($RequireStopped -and $active) { exit 3 }
        exit 0
    }
    # Parents first: prevent supervisor from restarting workers.
    foreach ($process in $handles) {
        if (-not $process.HasExited) {
            try { $process.Kill() }
            catch {
                # The QQ child may exit when its supervisor is stopped.
                $process.Refresh()
                if (-not $process.HasExited) { throw }
            }
        }
    }
    foreach ($process in $handles) { if (-not $process.WaitForExit(5000)) { throw 'Stop timeout' }; $process.Dispose() }
    $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and [IO.Path]::GetDirectoryName($_.ExecutablePath) -ieq $installFolder -and $_.Name -in @('QQ.exe','NapCatWinBootMain.exe') })
    if ($remaining.Count) { throw 'Processes still running' }
    foreach ($row in @(Get-CimInstance Win32_Process)) { if (Has-OwnedModule $row) { throw 'Owned QQ module still running' } }
    exit 0
} catch {
    if ($CheckOnly) { [Console]::Error.WriteLine(('Check failed at line {0}: {1}' -f $_.InvocationInfo.ScriptLineNumber, $_.Exception.GetType().Name)) }
    [Console]::Error.WriteLine('NapCat exit could not be confirmed.')
    exit 1
}
