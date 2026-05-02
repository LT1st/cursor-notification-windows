# Cursor command hook: reads JSON from stdin, forwards to report_task.py --hook
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Find-Python {
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "python not found on PATH"
}

$py = Find-Python
$script = Join-Path $Root "report_task.py"
# Read entire stdin (hook JSON)
try {
    $stdinReader = New-Object System.IO.StreamReader([System.Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
    $stdin = $stdinReader.ReadToEnd()
} catch {
    exit 0
}
if ([string]::IsNullOrWhiteSpace($stdin)) {
    exit 0
}
$stdin | & $py $script --hook
exit $LASTEXITCODE
