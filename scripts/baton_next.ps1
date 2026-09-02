$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Error "Baton requires Python 3.9 or newer."
    exit 2
}
if ($Python.Name -eq "py.exe") {
    & $Python.Source -3 (Join-Path $ScriptDir "baton_next.py") @args
} else {
    & $Python.Source (Join-Path $ScriptDir "baton_next.py") @args
}
exit $LASTEXITCODE
