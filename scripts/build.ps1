param([string]$BuildAlias = 'E:\YGOPro-Lite-Build')
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$source = Join-Path $workspace '.local\upstream'
if (Test-Path -LiteralPath $BuildAlias) {
    $link = Get-Item -LiteralPath $BuildAlias
    if ($link.LinkType -ne 'Junction' -or $link.Target -ne $source) {
        throw 'The ASCII build alias exists and does not point to this workspace source.'
    }
} else {
    New-Item -ItemType Junction -Path $BuildAlias -Target $source | Out-Null
}
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'A Visual Studio C++ build installation is required.' }
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\amd64\MSBuild.exe'
Push-Location -LiteralPath $BuildAlias
try {
    & '.\premake5.exe' vs2026 --no-audio --no-dxsdk --use-simd=none
    if ($LASTEXITCODE -ne 0) { throw 'Project generation failed.' }
    & $msbuild 'build\YGOPro.slnx' /m:6 /p:Configuration=Release /p:Platform=x64 /v:minimal /nologo /fileLogger '/fileLoggerParameters:LogFile=build-lite.log;Verbosity=normal'
    if ($LASTEXITCODE -ne 0) { throw 'Build failed; see .local/upstream/build-lite.log.' }
} finally { Pop-Location }
$runtime = Join-Path $workspace '.local\YGOPro-Lite'
$backup = Join-Path $workspace '.local\evidence\original-YGOPro.exe'
if (-not (Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath (Join-Path $runtime 'YGOPro.exe') -Destination $backup
}
Copy-Item -LiteralPath (Join-Path $source 'bin\release\x64\YGOPro.exe') -Destination (Join-Path $runtime 'YGOPro.exe')
Write-Output "Built and deployed: $runtime\YGOPro.exe"
