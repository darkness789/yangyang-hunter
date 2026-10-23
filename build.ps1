param(
    [string]$Python = 'py'
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$entry = Join-Path $projectRoot 'launcher.py'
$exe = Join-Path $projectRoot '羊羊狩猎者.exe'

if (-not (Test-Path -LiteralPath $entry)) {
    throw "Cannot find launcher: $entry"
}

Push-Location -LiteralPath $projectRoot
try {
    if ($Python -eq 'py') {
        & py -3.8 -c 'import PyInstaller, PIL; print(PyInstaller.__version__)'
        if ($LASTEXITCODE -ne 0) {
            throw 'Install build dependencies: py -3.8 -m pip install pyinstaller Pillow'
        }
        & py -3.8 -m PyInstaller --noconfirm --clean --onefile --windowed `
            --name '羊羊狩猎者' --distpath $projectRoot `
            --workpath (Join-Path $projectRoot 'build\pyinstaller') `
            --specpath (Join-Path $projectRoot 'build') $entry
    } else {
        & $Python -c 'import PyInstaller, PIL; print(PyInstaller.__version__)'
        if ($LASTEXITCODE -ne 0) {
            throw "Install build dependencies for ${Python}: pyinstaller Pillow"
        }
        & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
            --name '羊羊狩猎者' --distpath $projectRoot `
            --workpath (Join-Path $projectRoot 'build\pyinstaller') `
            --specpath (Join-Path $projectRoot 'build') $entry
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $exe)) {
        throw 'PyInstaller failed to create the executable.'
    }
    Write-Host "Built: $exe"
} finally {
    Pop-Location
}
