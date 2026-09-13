param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$python = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python.exe -ErrorAction Stop }
$program = Join-Path $PSScriptRoot 'src\trainer\app.py'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.local\YGOPro-Lite\YGOPro.exe'))) {
    throw 'Missing Lite runtime. See README.md to prepare and build the working copy.'
}
$launchArgs = @('"' + $program + '"')
if ($NoBrowser) { $launchArgs += '--no-browser' }
Start-Process -FilePath $python.Source -ArgumentList $launchArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
