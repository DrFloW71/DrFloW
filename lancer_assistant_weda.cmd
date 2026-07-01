@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PYTHONW_EXE=%VENV_DIR%\Scripts\pythonw.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
set "INSTALL_MARKER=%VENV_DIR%\.requirements-installed"
set "REQUIREMENTS_FILE=%PROJECT_DIR%requirements.txt"
set "DATA_DIR=%PROJECT_DIR%data"
set "LAUNCH_LOG=%DATA_DIR%\launch.log"
set "DEBUG_MODE=0"
set "SILENT_MODE=0"
set "NEED_INSTALL=0"

if /I "%~1"=="--debug" set "DEBUG_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"

cd /d "%PROJECT_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" >nul 2>nul
call :log "Demarrage du lanceur."

if not exist "%PYTHON_EXE%" (
    echo Creation de l'environnement Python local...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        call :fail "Impossible de creer l'environnement Python."
    )
)

if not exist "%INSTALL_MARKER%" set "NEED_INSTALL=1"
if "%NEED_INSTALL%"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "if ((Get-Item -LiteralPath $env:REQUIREMENTS_FILE).LastWriteTimeUtc -gt (Get-Item -LiteralPath $env:INSTALL_MARKER).LastWriteTimeUtc) { exit 0 } exit 1"
    if not errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" (
    echo Installation des dependances...
    "%PIP_EXE%" install -r "%PROJECT_DIR%requirements.txt"
    if errorlevel 1 (
        call :fail "Installation des dependances incomplete."
    )
    echo ok>"%INSTALL_MARKER%"
)

echo Lancement de DrFloW - Assistant local de consultation medicale...

if "%DEBUG_MODE%"=="1" (
    "%PYTHON_EXE%" "%PROJECT_DIR%app.py"
    if errorlevel 1 (
        echo.
        echo L'application s'est arretee avec une erreur.
        pause
    )
    exit /b %errorlevel%
)

if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=%PYTHON_EXE%"

start "" /D "%PROJECT_DIR%" "%PYTHONW_EXE%" "%PROJECT_DIR%app.py"
if errorlevel 1 (
    call :fail "Impossible de lancer l'application."
)

call :log "Application lancee en mode graphique."
exit /b 0

:log
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" >nul 2>nul
>>"%LAUNCH_LOG%" echo [%DATE% %TIME%] %~1
exit /b 0

:fail
call :log "ERREUR: %~1"
if not "%SILENT_MODE%"=="1" (
    echo.
    echo %~1
    pause
)
exit /b 1
