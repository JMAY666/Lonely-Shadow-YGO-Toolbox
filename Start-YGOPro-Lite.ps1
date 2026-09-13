$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.local\YGOPro-Lite'
$program = Join-Path $runtime 'YGOPro.exe'
if (-not (Test-Path -LiteralPath $program)) {
    throw 'The local Lite build is not present. Follow README.md to prepare and build it.'
}
Start-Process -FilePath $program -WorkingDirectory $runtime
