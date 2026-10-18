# Установщик, проверка LM Studio, модель по видеопамяти — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** раздел 18 спека: `JobFinder-Setup.exe`, окно «Getting ready», модель 8B/3B по видеопамяти, данные установленной версии в `%LOCALAPPDATA%`.

**Architecture:** `config` различает исходники и сборку (`FROZEN`, `DATA_DIR`, `LOCK_PATH`); `hardware.py` — видеопамять и модель;
`llm` берёт модель из настроек; `ready_window.py` — окно проверки; `installer.py` (+ `packaging/`) — установка и удаление;
`build.ps1` — сборка.

**Tech Stack:** Python 3.11, PySide6, PyInstaller (только сборка), winreg, PowerShell (ярлыки), pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 18.

## Global Constraints
- Модели: `mistralai/ministral-3-8b` (по умолчанию, ≥ 7,5 ГБ или неизвестно), `mistralai/ministral-3-3b` (< 7,5 ГБ).
- Папка программы `%LOCALAPPDATA%\Programs\Job Finder`, данных `%LOCALAPPDATA%\Job Finder`; переменные для проверок:
  `JOB_FINDER_DATA`, `JOB_FINDER_INSTALL_DIR`, `JOB_FINDER_SHORTCUTS_DIR`.
- Надписи: «Getting ready», «Get LM Studio», «Download model», «Check again», «Continue», «Continue anyway»,
  «Open Job Finder now?», «Uninstall Job Finder».
- У автора (исходники, 12 ГБ) — те же папка данных и ключ оценки. Тесты не трогают реестр, ярлыки и папки пользователя.
- Без кириллицы в коде; сигналы Qt — к методам; код выхода тестов 0; коммит с `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Установка поверх запущенного приложения — понятное сообщение, ничего не сломано.
2. Повторная установка (обновление) — данные на месте, старые файлы программы заменены.
3. `lms get` долго или с ошибкой (нет сети) — окно не зависает, можно продолжить.
4. Видеопамять не читается (нет ключей реестра, виртуальная машина) — модель 8B, без падения.
5. Две версии (исходники и установленная) одновременно — вторая открывает окно первой, а не запускается.

---

### Task 1: Папка данных, модель по видеопамяти
**Files:** `job_finder/config.py`, создать `job_finder/hardware.py`; `job_finder/settings.py` (поле `model`), `job_finder/llm.py`,
`job_finder/worker.py`, `job_finder/__main__.py` (папка данных, блокировка); tests `test_config.py`, `test_hardware.py`, `test_llm.py`.
**Interfaces:** `config.data_dir(frozen: bool, environ) -> Path`; `hardware.vram_gb(read=...) -> float | None`;
`hardware.model_for_vram(gb) -> str`; `llm.model_name(s) -> str`; `llm.prepare(model: str)`.
- [ ] Тесты: `test_data_dir`; `test_model_for_vram`; `test_vram_from_registry_values`; `test_fingerprint_uses_model`;
  `test_prepare_reloads_another_model`. Run — FAIL. Реализация. Run — PASS. Commit `Data folder for the installed app; model by video memory`.

### Task 2: Окно «Getting ready»
**Files:** создать `job_finder/ready_window.py`, `tests/test_ready_window.py`; `job_finder/__main__.py`.
**Interfaces:** `lms_installed() -> bool`; `model_downloaded(model) -> bool`; `everything_ready(model) -> bool`; `ReadyDialog(model)`.
- [ ] Тесты: без LM Studio; без модели; скачивание (подменённый запуск) → проверка заново; всё есть — окна нет; окно освобождается.
  Run — FAIL. Реализация. Run — PASS. Commit `Getting ready window: LM Studio and the model`.

### Task 3: Установщик и удаление, сборка
**Files:** создать `job_finder/installer.py`, `packaging/run_app.py`, `packaging/run_setup.py`, `build.ps1`, `tests/test_installer.py`;
`job_finder/__main__.py` (`--uninstall`), `.gitignore`.
- [ ] Тесты: установка из архива во временную папку (старые файлы заменены, ярлыки — подменённой функцией); занятая папка →
  понятная ошибка; удаление (ярлыки удалены, удаление папки запланировано). Run — FAIL. Реализация. Run — PASS.
- [ ] Сборка `build.ps1`; установщик с `JOB_FINDER_INSTALL_DIR`/`JOB_FINDER_SHORTCUTS_DIR` во временную папку; собранное
  приложение с `JOB_FINDER_DATA` во временную папку стартует. Commit `Installer: JobFinder-Setup.exe`.

### Task 4: Документация
- [ ] README: установка через `JobFinder-Setup.exe` (SmartScreen, LM Studio, «Getting ready», 8B/3B — 3B слабее, оценки могут
  немного отличаться), обновление, удаление, ошибки; «Running from source» для разработчиков. how-it-works. Commit `Docs for the installer`.

Затем ревью; проверка автором; публикация релиза и слияние — с согласия автора.
