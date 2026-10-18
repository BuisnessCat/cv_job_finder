# Builds dist\JobFinder-Setup.exe (for the developer): the app folder with PyInstaller, zipped into a one-file setup.
# Run: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$icon = Join-Path $root "job_finder\icon.ico"
$build = Join-Path $root "build"

& $python -m pip install --quiet "pyinstaller==6.11.1"
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller" }

# 1. The app: a folder with "Job Finder.exe", Python and the libraries inside
& $python -m PyInstaller --noconfirm --clean --windowed --name "Job Finder" --icon $icon `
    --add-data "$icon;job_finder" --paths $root `
    --distpath (Join-Path $build "app") --workpath (Join-Path $build "work-app") --specpath $build `
    (Join-Path $root "packaging\run_app.py")
if ($LASTEXITCODE -ne 0) { throw "The app build failed" }

# 2. The app folder as one archive, carried inside the setup
$archive = Join-Path $build "Job Finder.zip"
Compress-Archive -Path (Join-Path $build "app\Job Finder\*") -DestinationPath $archive -Force

# 3. The setup: one file; it unpacks the archive into the user's Programs folder and makes the shortcuts
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name "JobFinder-Setup" --icon $icon `
    --add-data "$archive;." --paths $root `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $build "work-setup") --specpath $build `
    (Join-Path $root "packaging\run_setup.py")
if ($LASTEXITCODE -ne 0) { throw "The setup build failed" }
Write-Output "Done: dist\JobFinder-Setup.exe"
