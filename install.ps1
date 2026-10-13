# Setup: virtual environment, dependencies and a "Job Finder" shortcut on the desktop.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    py -3.11 -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv (Python 3.11 is required)" }
}
& $python -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install dependencies" }

$desktop = [Environment]::GetFolderPath("Desktop")
# The shortcut of the earlier Russian version; the name is spelled with char codes to keep this file ASCII
$oldName = -join ([char[]](0x41F,0x43E,0x434,0x431,0x43E,0x440,0x20,0x432,0x430,0x43A,0x430,0x43D,0x441,0x438,0x439)) + ".lnk"
Remove-Item (Join-Path $desktop $oldName) -ErrorAction SilentlyContinue
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Job Finder.lnk"))
$shortcut.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
$shortcut.Arguments = "-m job_finder"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = (Join-Path $root "job_finder\icon.ico") + ",0"
$shortcut.Description = "Job Finder"
$shortcut.Save()
Write-Output "Done: a Job Finder shortcut is on the desktop"
