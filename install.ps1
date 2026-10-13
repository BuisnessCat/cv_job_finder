# Установка: виртуальное окружение, зависимости и ярлык «Подбор вакансий» на рабочем столе.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    py -3.11 -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать .venv (нужен Python 3.11)" }
}
& $python -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Не удалось поставить зависимости" }

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Подбор вакансий.lnk"))
$shortcut.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
$shortcut.Arguments = "-m job_finder"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Подбор вакансий"
$shortcut.Save()
Write-Output "Готово: ярлык «Подбор вакансий» на рабочем столе"
