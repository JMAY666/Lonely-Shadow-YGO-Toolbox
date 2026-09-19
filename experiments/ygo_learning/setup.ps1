# Install only this experiment's pinned Windows/AMD training environment.
$ErrorActionPreference = 'Stop'
$studentRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$studentEnvironment = Join-Path $studentRoot '.local/ygo-learning/.venv'
$studentPython = Join-Path $studentEnvironment 'Scripts/python.exe'
$studentLock = Join-Path $PSScriptRoot 'requirements-rocm-windows.lock.txt'

Get-Command uv -ErrorAction Stop | Out-Null
if (-not (Test-Path -LiteralPath $studentPython)) {
    & uv venv --python 3.13 $studentEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python environment' }
}
& $studentPython -c 'import sys; assert sys.version_info[:2] == (3, 13), "CPython 3.13 is required"'
if ($LASTEXITCODE -ne 0) { throw 'Unexpected Python version; the existing environment was preserved' }
& uv pip sync --no-cache --link-mode copy --python $studentPython $studentLock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& uv pip check --python $studentPython
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed' }
Write-Output "Student environment ready: $studentPython"
Write-Output 'Next: prepare_smoke_data.py using the pilot Python, then gpu_smoke.py using this environment.'
