@echo off
REM ── Take project dir from the current location of this .bat file ───────────
SET "PROJECT_DIR=%~dp0"
IF "%PROJECT_DIR:~-1%"=="\" SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

REM ── Delete old GoGreen_BE_DIR (if present) and store the new path ──────────
REG QUERY "HKCU\Environment" /v GoGreen_BE_DIR >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo Existing GoGreen_BE_DIR found. Removing old value...
    REG DELETE "HKCU\Environment" /v GoGreen_BE_DIR /F >nul 2>&1
)
SET "GoGreen_BE_DIR="
SETX GoGreen_BE_DIR "%PROJECT_DIR%" >nul
REM SETX only affects NEW terminals, so also set it for this session
SET "GoGreen_BE_DIR=%PROJECT_DIR%"
echo GoGreen_BE_DIR set to: %GoGreen_BE_DIR%

cd /d "%GoGreen_BE_DIR%"
call venv\Scripts\activate.bat

echo ========================================
echo  Go Green - Server Setup
echo ========================================


REM ── Install dependencies only on first run ─────────────────────────────────
IF EXIST "%PROJECT_DIR%\.deps_installed" (
    echo [OK] Dependencies already installed. Skipping...
) ELSE (
    IF EXIST "%PROJECT_DIR%\requirements.txt" (
        echo Installing dependencies, please wait...
        pip install -r "%PROJECT_DIR%\requirements.txt"
        IF ERRORLEVEL 1 (
            echo.
            echo [ERROR] pip install failed. Check your internet connection
            echo         or requirements.txt and try again.
            pause
            exit /b 1
        )
        echo. > "%PROJECT_DIR%\.deps_installed"
        echo [OK] Dependencies installed successfully.
    ) ELSE (
        echo [WARN] requirements.txt not found. Skipping install.
    )
)
python setup_dialog.py
exit /b

IF NOT EXIST ".env" (
    echo Setup was cancelled. Exiting.
    pause
    exit /b 0
)

SET RUN_MODE=both
FOR /F "tokens=1,2 delims==" %%A IN (.env) DO (
    IF "%%A"=="RUN_MODE" SET RUN_MODE=%%B
)

echo  Selected mode: %RUN_MODE%

REM ── Load server state to skip already-running servers ──────────────────────
SET DJANGO_RUNNING=0
SET FASTAPI_RUNNING=0
IF EXIST ".server_state.json" (
    FOR /F "tokens=*" %%L IN (.server_state.json) DO (
        echo %%L | findstr /C:"\"django\": true" >nul && SET DJANGO_RUNNING=1
        echo %%L | findstr /C:"\"fastapi\": true" >nul && SET FASTAPI_RUNNING=1
    )
)

REM ── Run migrations only when launching Django for first time ───────────────
IF "%RUN_MODE%"=="both"    GOTO check_django_migrate
IF "%RUN_MODE%"=="django"  GOTO check_django_migrate
GOTO skip_migrations

:check_django_migrate
IF "%DJANGO_RUNNING%"=="0" (
    echo Running Django migrations...
    python manage.py makemigrations
    python manage.py migrate
)

:skip_migrations

REM ── The dialog already launched the servers. This script just keeps the ─────
REM ── window alive so the user sees the echo output. ─────────────────────────
IF "%RUN_MODE%"=="both" (
    IF "%DJANGO_RUNNING%"=="0"  echo Django  started -> http://localhost:8000
    IF "%FASTAPI_RUNNING%"=="0" echo FastAPI started -> http://localhost:8001
    IF "%DJANGO_RUNNING%"=="1"  echo Django  already running -> http://localhost:8000
    IF "%FASTAPI_RUNNING%"=="1" echo FastAPI already running -> http://localhost:8001
)
IF "%RUN_MODE%"=="django" (
    IF "%DJANGO_RUNNING%"=="0"  echo Django started -> http://localhost:8000
    IF "%DJANGO_RUNNING%"=="1"  echo Django already running -> http://localhost:8000
)
IF "%RUN_MODE%"=="fastapi" (
    IF "%FASTAPI_RUNNING%"=="0"  echo FastAPI started -> http://localhost:8001
    IF "%FASTAPI_RUNNING%"=="1"  echo FastAPI already running -> http://localhost:8001
)

echo ========================================
pause