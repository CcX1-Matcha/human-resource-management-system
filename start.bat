@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 app.py --open
    goto end
)
set "HRM_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%HRM_PYTHON%" (
    "%HRM_PYTHON%" -X utf8 app.py --open
    goto end
)
where python >nul 2>nul
if not errorlevel 1 (
    python -X utf8 app.py --open
    goto end
)
echo 未找到 Python。请安装 Python 3.10 或更新版本，然后重新双击本文件。
echo 下载地址：https://www.python.org/downloads/windows/
:end
pause
