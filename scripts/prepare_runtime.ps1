$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $workspace '.local\YGOPro-Lite'
$evidence = Join-Path $workspace '.local\evidence'
$resolvedRuntime = (Resolve-Path -LiteralPath $runtime).Path
$expectedRuntime = [IO.Path]::GetFullPath((Join-Path $workspace '.local\YGOPro-Lite'))
if ($resolvedRuntime -ne $expectedRuntime -or $resolvedRuntime -eq 'E:\Game\YGOPro') {
    throw 'The runtime path did not resolve to the independent workspace copy.'
}
if (-not (Test-Path -LiteralPath (Join-Path $evidence 'source-baseline.json'))) {
    throw 'A verified original-file baseline is required before removing copied resources.'
}

# These are copied audio assets and install/association helpers, never user decks or replays.
$removePaths = @('sound', 'Uninst.exe', '系统关联.exe', 'icon\yrp.ico')
foreach ($relative in $removePaths) {
    $candidate = Join-Path $runtime $relative
    if (Test-Path -LiteralPath $candidate) {
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if (-not $resolved.StartsWith($resolvedRuntime + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Removal escaped the workspace copy: $relative"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
        Write-Output "Removed copied resource: $relative"
    }
}

$configPath = Join-Path $runtime 'system.conf'
$configBackup = Join-Path $evidence 'original-system.conf'
if (-not (Test-Path -LiteralPath $configBackup)) {
    Copy-Item -LiteralPath $configPath -Destination $configBackup
}
$config = [IO.File]::ReadAllText($configPath)
$settings = [ordered]@{
    use_d3d = '0'; enable_sound = '0'; enable_music = '0'; sound_volume = '0'; music_volume = '0'
    bot_room_public = '0'; enable_bot_mode = '1'; auto_save_replay = '0'
    nickname = 'Trainer'; lasthost = '127.0.0.1'; lastport = '0'; errorlog = '3'
}
foreach ($entry in $settings.GetEnumerator()) {
    $pattern = '(?m)^' + [Regex]::Escape($entry.Key) + '\s*=.*$'
    $config = [Regex]::Replace($config, $pattern, $entry.Key + ' = ' + $entry.Value)
}
[IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
Write-Output "Prepared isolated runtime: $runtime"
