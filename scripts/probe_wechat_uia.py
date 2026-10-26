"""Read-only, bounded Windows UIA diagnostics; never outputs control names or text.

Run with the project Python: scripts/probe_wechat_uia.py --group "<exact title>".
A candidate control tree is NOT proof of successful message acquisition.
"""
import argparse
import base64
import json
import os
import subprocess
import sys


POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$group = $env:CAMPUSFLOW_PROBE_GROUP
$processes = @(Get-Process -Name Weixin,WeChat -ErrorAction SilentlyContinue)
$ids = @($processes | ForEach-Object { $_.Id })
$processInfo = @($processes | ForEach-Object {
    $version = $null
    try { $version = $_.MainModule.FileVersionInfo.FileVersion } catch {}
    @{pid=$_.Id; session_id=$_.SessionId; version=$version}
})
function Measure-Tree($element, $walker) {
    $counts = @{}
    $nodes = 0
    $truncated = $false
    $errorCode = $null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $stack = [Collections.Generic.Stack[object]]::new()
    $stack.Push(@{node=$element; depth=0})
    try {
        while ($stack.Count -gt 0) {
            if ($nodes -ge 1000 -or $timer.Elapsed.TotalSeconds -ge 4) {
                $truncated = $true
                break
            }
            $entry = $stack.Pop()
            $child = $walker.GetFirstChild($entry.node)
            while ($null -ne $child) {
                if ($nodes -ge 1000 -or $timer.Elapsed.TotalSeconds -ge 4) {
                    $truncated = $true
                    break
                }
                $type = $child.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
                if (-not $counts.ContainsKey($type)) { $counts[$type] = 0 }
                $counts[$type]++
                $nodes++
                if ($entry.depth -lt 20) {
                    $stack.Push(@{node=$child; depth=$entry.depth+1})
                } else { $truncated = $true }
                $child = $walker.GetNextSibling($child)
            }
        }
    } catch { $errorCode = 'uia_error' }
    return @{controls=$counts; nodes=$nodes; truncated=$truncated; error=$errorCode}
}
$windows = @()
$ignored = 0
if ($ids.Count -gt 0) {
    # Some providers omit windows from UIA RootElement. Enumerate native handles.
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class WechatProbeWindows {
    public delegate bool Callback(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(Callback c, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    public static IntPtr[] Handles() {
        var result = new List<IntPtr>();
        EnumWindows((h,l) => { result.Add(h); return true; }, IntPtr.Zero);
        return result.ToArray();
    }
}
"@
    foreach ($handle in [WechatProbeWindows]::Handles()) {
        $windowPid = [uint32]0
        [void][WechatProbeWindows]::GetWindowThreadProcessId($handle, [ref]$windowPid)
        if ($windowPid -notin $ids) { continue }
        # Names are compared in memory only, and never included in diagnostics.
        $title = [Text.StringBuilder]::new(512)
        [void][WechatProbeWindows]::GetWindowText($handle, $title, 512)
        $name = $title.ToString()
        $kind = if ($name -ceq $group) {'target'} elseif ($name -in @('微信','Weixin','WeChat')) {'main'} else {'other'}
        if ($kind -eq 'other') { $ignored++; continue }
        try { $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle) }
        catch {
            $windows += @{kind=$kind; controls=@{}; error='element_unavailable'; truncated=$false}
            continue
        }
        $control = Measure-Tree $element ([System.Windows.Automation.TreeWalker]::ControlViewWalker)
        $raw = Measure-Tree $element ([System.Windows.Automation.TreeWalker]::RawViewWalker)
        $windows += @{
            kind=$kind; pid=$windowPid
            visible=[WechatProbeWindows]::IsWindowVisible($handle)
            minimized=[WechatProbeWindows]::IsIconic($handle)
            offscreen=$element.Current.IsOffscreen
            controls=$control.controls; nodes=$control.nodes
            raw_controls=$raw.controls; raw_nodes=$raw.nodes
            truncated=($control.truncated -or $raw.truncated)
            error=$(if ($control.error -or $raw.error) {'uia_error'} else {$null})
        }
    }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
@{
    windows=@($windows); processes=@($processInfo); ignored_windows=$ignored
    probe_session_id=(Get-Process -Id $PID).SessionId
    probe_elevated=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} | ConvertTo-Json -Depth 8 -Compress
"""


def classify(windows):
    targets = [w for w in windows if w.get("kind") == "target"]
    if not targets:
        return "target_window_missing"
    if len(targets) != 1:
        return "target_window_ambiguous"
    window = targets[0]
    if window.get("truncated") or window.get("error"):
        return "scan_inconclusive"
    for key in ("controls", "raw_controls"):
        types = window.get(key, {})
        if types.get("List", 0) and any(types.get(t, 0) for t in ("ListItem", "CheckBox", "Text")):
            return "requires_message_verification"
    return "message_controls_unavailable"


def probe(group, timeout=25, runner=subprocess.run, platform=sys.platform):
    if platform != "win32":
        return {"status": "unsupported_platform", "windows": []}
    encoded = base64.b64encode(POWERSHELL.encode("utf-16-le")).decode("ascii")
    env = os.environ.copy()
    env["CAMPUSFLOW_PROBE_GROUP"] = group
    # In-process UIA calls can hang inside a provider; isolate with a hard timeout.
    try:
        result = runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, encoding="utf-8", timeout=timeout, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            return {"status": "probe_failed", "windows": []}
        data = json.loads(result.stdout.lstrip("\ufeff"))
        data["status"] = classify(data["windows"])
        return data
    except subprocess.TimeoutExpired:
        return {"status": "probe_timeout", "windows": []}
    except (OSError, ValueError, KeyError, TypeError):
        # Do not echo provider exceptions/stdout/stderr: they may contain UI data.
        return {"status": "probe_failed", "windows": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, help="Exact independent chat window title; never logged")
    parser.add_argument("--timeout", type=int, default=25, choices=range(5, 61), metavar="5..60")
    args = parser.parse_args()
    report = probe(args.group, args.timeout)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    # Gate is deliberately not passed by finding controls. W02 must verify messages.
    return 0 if report["status"] == "requires_message_verification" else 2


if __name__ == "__main__":
    raise SystemExit(main())
