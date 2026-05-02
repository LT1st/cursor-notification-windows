<#!
  Manual / rule trigger: report a task state and optionally show toast on terminal state.
  Example:
    .\hook_report.ps1 -Session "sess1" -Task "task1" -Status FINISHED -Title "Refactor done"
#>
param(
    [string]$Session = "manual-session",
    [string]$Task = "",
    [string]$Status = "FINISHED",
    [string]$Title = "Cursor task",
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "python not found on PATH"
}

$py = Find-Python
$script = Join-Path $Root "report_task.py"
if ($Task) {
    & $py $script --session $Session --task $Task --status $Status --title $Title --message $Message
} else {
    & $py $script --session $Session --status $Status --title $Title --message $Message
}
