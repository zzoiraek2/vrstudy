$ErrorActionPreference = "Stop"

$AppVersion = (python -c "from vrstudy import __version__; print(__version__)").Trim()
$Root = (Resolve-Path ".").Path
$DistDir = Join-Path $Root "dist"
$BuildDir = Join-Path $Root "build"
$ReleaseDir = Join-Path $Root "release"
$PyInstallerDistDir = Join-Path $BuildDir "pyinstaller-dist"
$PyInstallerWorkDir = Join-Path $BuildDir "pyinstaller-work"
$BuildDataSnapshotDir = $null
$BuildDataSourceDir = $null

function Assert-ChildPath {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Parent
  )
  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $fullParent = [System.IO.Path]::GetFullPath($Parent)
  if (-not $fullParent.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $fullParent = $fullParent + [System.IO.Path]::DirectorySeparatorChar
  }
  if (-not $fullPath.StartsWith($fullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to operate outside expected directory: $fullPath"
  }
}

function Reset-Directory {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Parent
  )
  Assert-ChildPath -Path $Path -Parent $Parent
  if (Test-Path -LiteralPath $Path) {
    Remove-Item -LiteralPath $Path -Recurse -Force
  }
  New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Test-ByteRangeLockAvailable {
  param([Parameter(Mandatory=$true)][string]$Path)
  $stream = $null
  try {
    $stream = [System.IO.File]::Open(
      $Path,
      [System.IO.FileMode]::OpenOrCreate,
      [System.IO.FileAccess]::ReadWrite,
      [System.IO.FileShare]::ReadWrite
    )
    $stream.Lock(0, 1)
    $stream.Unlock(0, 1)
    return $true
  } catch {
    return $false
  } finally {
    if ($stream) {
      $stream.Close()
    }
  }
}

function Assert-DataSourceNotInUse {
  param([Parameter(Mandatory=$true)][string]$DataDir)
  $lockPath = Join-Path $DataDir "vrstudy.lock"
  if ((Test-Path -LiteralPath $lockPath) -and -not (Test-ByteRangeLockAvailable -Path $lockPath)) {
    throw "Cannot build while VRStudy is using data. Close the app and retry. Locked file: $lockPath"
  }
}

function Checkpoint-DbFile {
  param([Parameter(Mandatory=$true)][string]$DbPath)
  if (Test-Path -LiteralPath $DbPath) {
    $env:VRSTUDY_CHECKPOINT_DB = $DbPath
    try {
      python -c "import os, duckdb; p=os.environ['VRSTUDY_CHECKPOINT_DB']; con=duckdb.connect(p); con.execute('CHECKPOINT'); con.close()"
    } finally {
      Remove-Item Env:\VRSTUDY_CHECKPOINT_DB -ErrorAction SilentlyContinue
    }
  }
}

function Get-LiveDataSourceDir {
  $distDataDir = Join-Path $DistDir "data"
  if (Test-Path -LiteralPath $distDataDir) {
    return $distDataDir
  }
  return (Join-Path $Root "data")
}

function New-BuildDataSnapshot {
  if ($script:BuildDataSnapshotDir -and (Test-Path -LiteralPath $script:BuildDataSnapshotDir)) {
    return $script:BuildDataSnapshotDir
  }

  $sourceDataDir = Get-LiveDataSourceDir
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $snapshotDir = Join-Path $BuildDir "data-snapshots\$stamp"
  Reset-Directory -Path $snapshotDir -Parent $BuildDir

  if (Test-Path -LiteralPath $sourceDataDir) {
    Assert-DataSourceNotInUse -DataDir $sourceDataDir
    Restore-LocalTelegramSettingsToDataDir -DataDir $sourceDataDir
    Checkpoint-DbFile -DbPath (Join-Path $sourceDataDir "vrstudy.duckdb")
    Copy-DataFolder -SourceDir $sourceDataDir -TargetDir $snapshotDir
    Checkpoint-DbFile -DbPath (Join-Path $snapshotDir "vrstudy.duckdb")
    Write-Host "Snapshotted build data from $sourceDataDir to: $snapshotDir"
  } else {
    Write-Host "No existing data folder found. Created empty build data snapshot: $snapshotDir"
  }

  $script:BuildDataSnapshotDir = $snapshotDir
  $script:BuildDataSourceDir = $snapshotDir
  return $script:BuildDataSnapshotDir
}

function Get-BuildDataSourceDir {
  if ($script:BuildDataSourceDir -and (Test-Path -LiteralPath $script:BuildDataSourceDir)) {
    return $script:BuildDataSourceDir
  }
  return (New-BuildDataSnapshot)
}

function Restore-LocalDistData {
  $sourceDataDir = Get-BuildDataSourceDir
  if (-not (Test-Path -LiteralPath $sourceDataDir)) {
    return
  }
  $targetDataDir = Join-Path $DistDir "data"
  New-Item -ItemType Directory -Path $targetDataDir -Force | Out-Null
  Copy-DataFolder -SourceDir $sourceDataDir -TargetDir $targetDataDir
  Restore-LocalTelegramSettingsToDataDir -DataDir $targetDataDir
  Write-Host "Synced local dist data from $sourceDataDir to: $targetDataDir"
}

function Restore-LocalTelegramSettingsToDataDir {
  param([Parameter(Mandatory=$true)][string]$DataDir)
  $rootTelegram = Join-Path (Join-Path $Root "data") "telegram_settings.json"
  $targetTelegram = Join-Path $DataDir "telegram_settings.json"
  if ((Test-Path -LiteralPath $targetTelegram) -or -not (Test-Path -LiteralPath $rootTelegram)) {
    return
  }
  New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
  Copy-Item -LiteralPath $rootTelegram -Destination $targetTelegram -Force
  Write-Host "Restored local Telegram settings to: $targetTelegram"
}

function Checkpoint-DataDb {
  $dbPath = Join-Path (Get-BuildDataSourceDir) "vrstudy.duckdb"
  Checkpoint-DbFile -DbPath $dbPath
}

function Copy-AppFiles {
  param([Parameter(Mandatory=$true)][string]$TargetDir)
  Copy-Item -LiteralPath (Join-Path $DistDir "vrstudy.exe") -Destination (Join-Path $TargetDir "vrstudy.exe") -Force
  Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination (Join-Path $TargetDir "README.md") -Force
  Copy-Item -LiteralPath (Join-Path $Root "CHANGELOG.md") -Destination (Join-Path $TargetDir "CHANGELOG.md") -Force
}

function Copy-DataFolder {
  param(
    [Parameter(Mandatory=$true)][string]$SourceDir,
    [Parameter(Mandatory=$true)][string]$TargetDir
  )
  if (-not (Test-Path -LiteralPath $SourceDir)) {
    return
  }
  $sourceFull = [System.IO.Path]::GetFullPath($SourceDir)
  New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
  Get-ChildItem -LiteralPath $SourceDir -Recurse -Force | ForEach-Object {
    $name = $_.Name
    if ($name -eq "vrstudy.lock" -or $name -like "*.wal" -or $name -like "*.wal.bad-*") {
      return
    }
    $relative = $_.FullName.Substring($sourceFull.Length).TrimStart("\", "/")
    $destination = Join-Path $TargetDir $relative
    if ($_.PSIsContainer) {
      New-Item -ItemType Directory -Path $destination -Force | Out-Null
    } else {
      $parent = Split-Path $destination -Parent
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
  }
}

function Copy-CurrentDataPackage {
  param([Parameter(Mandatory=$true)][string]$TargetDataDir)
  $sourceDataDir = Get-BuildDataSourceDir
  $sourceDb = Join-Path $sourceDataDir "vrstudy.duckdb"
  $sourceProfiles = Join-Path $sourceDataDir "profiles"
  New-Item -ItemType Directory -Path $TargetDataDir -Force | Out-Null
  if (Test-Path -LiteralPath $sourceDb) {
    Copy-Item -LiteralPath $sourceDb -Destination (Join-Path $TargetDataDir "vrstudy.duckdb") -Force
  }
  if (Test-Path -LiteralPath $sourceProfiles) {
    Copy-Item -LiteralPath $sourceProfiles -Destination (Join-Path $TargetDataDir "profiles") -Recurse -Force
  }
}

function Write-PackageNote {
  param(
    [Parameter(Mandatory=$true)][string]$TargetDir,
    [Parameter(Mandatory=$true)][string]$PackageKind
  )
  $notePath = Join-Path $TargetDir "PACKAGE.txt"
  if ($PackageKind -eq "empty") {
    @"
VRStudy v$AppVersion empty package

Use this for a new user or a new clean setup.
Run vrstudy.exe. The app will create data\ automatically on first launch.
"@ | Set-Content -LiteralPath $notePath -Encoding UTF8
  } else {
    @"
VRStudy v$AppVersion data-included package

Use this when transferring the current configured data.
This package includes data\vrstudy.duckdb, data\profiles\vr, and data\profiles\infinite.
Telegram settings are intentionally not included. Enter Bot Token and Chat ID on each PC.
Kiwoom API credentials under data\secrets are intentionally not included.
Automatic backups are not included; the receiving app will create its own data\backups folder.
Do not add vrstudy.lock, *.wal, or *.wal.bad-* files to distribution packages.
"@ | Set-Content -LiteralPath $notePath -Encoding UTF8
  }
}

function New-ReleasePackages {
  Checkpoint-DataDb
  New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
  $emptyDir = Join-Path $ReleaseDir "VRStudy-v$AppVersion-empty"
  $dataDir = Join-Path $ReleaseDir "VRStudy-v$AppVersion-with-data"
  Reset-Directory -Path $emptyDir -Parent $ReleaseDir
  Reset-Directory -Path $dataDir -Parent $ReleaseDir

  Copy-AppFiles -TargetDir $emptyDir
  Write-PackageNote -TargetDir $emptyDir -PackageKind "empty"

  Copy-AppFiles -TargetDir $dataDir
  Copy-CurrentDataPackage -TargetDataDir (Join-Path $dataDir "data")
  Write-PackageNote -TargetDir $dataDir -PackageKind "with-data"

  foreach ($dir in @($emptyDir, $dataDir)) {
    $zipPath = "$dir.zip"
    Assert-ChildPath -Path $zipPath -Parent $ReleaseDir
    if (Test-Path -LiteralPath $zipPath) {
      Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $dir "*") -DestinationPath $zipPath -Force
  }

  Write-Host "Release package: $emptyDir.zip"
  Write-Host "Release package: $dataDir.zip"
}

python -m pip install -r requirements-dev.txt

New-BuildDataSnapshot | Out-Null

Reset-Directory -Path $PyInstallerDistDir -Parent $BuildDir
Reset-Directory -Path $PyInstallerWorkDir -Parent $BuildDir

python -m PyInstaller `
  --onefile `
  --windowed `
  --clean `
  --name vrstudy `
  --distpath $PyInstallerDistDir `
  --workpath $PyInstallerWorkDir `
  --specpath $BuildDir `
  --hidden-import uuid `
  --hidden-import tkinter `
  --collect-all duckdb `
  --collect-data certifi `
  vrstudy_app.py

New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
$BuiltExeFromBuild = Resolve-Path (Join-Path $PyInstallerDistDir "vrstudy.exe")
Copy-Item -LiteralPath $BuiltExeFromBuild.Path -Destination (Join-Path $DistDir "vrstudy.exe") -Force

$BuiltExe = Resolve-Path (Join-Path $DistDir "vrstudy.exe")
$VersionedExe = Join-Path (Split-Path $BuiltExe.Path) "vrstudy-v$AppVersion.exe"
Copy-Item -LiteralPath $BuiltExe.Path -Destination $VersionedExe -Force

Restore-LocalDistData

New-ReleasePackages

Write-Host ""
Write-Host "Built executable: $($BuiltExe.Path)"
Write-Host "Versioned copy: $VersionedExe"
