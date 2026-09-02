$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = $null
foreach ($ConfigName in @(".baton-config", ".loop-team-config")) {
    $ConfigPath = Join-Path $HOME $ConfigName
    if (Test-Path $ConfigPath) {
        $Line = Get-Content $ConfigPath | Where-Object { $_ -match '^\s*base_dir=' } | Select-Object -Last 1
        if ($Line) {
            $BaseDir = ($Line -replace '^\s*base_dir=', '').Trim()
            break
        }
    }
}
if (-not $BaseDir) {
    $BaseDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
}
$Status = Join-Path $BaseDir "hooks\baton_status.py"
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Error "Baton requires Python 3.9 or newer."
    exit 2
}
if ($Python.Name -eq "py.exe") {
    & $Python.Source -3 $Status
} else {
    & $Python.Source $Status
}
exit $LASTEXITCODE
