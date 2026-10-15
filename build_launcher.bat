@echo off
REM ── Take project dir from the current location of this .bat file ───────────
SET "PROJECT_DIR=%~dp0"
IF "%PROJECT_DIR:~-1%"=="\" SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

cd /d "%PROJECT_DIR%"
call venv\Scripts\activate.bat

echo ========================================
echo  Go Green - Building Backend Launcher
echo ========================================

pyinstaller ^
  --onefile ^
  --windowed ^
  --name "GoGreen Backend" ^
  --add-data "local_folder;local_folder" ^
  setup_dialog.py

IF ERRORLEVEL 1 (
    echo.
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo [OK] Build complete.
echo Creating desktop shortcut...

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop');" ^
  "$sc = $ws.CreateShortcut($desktop + '\GoGreen Backend.lnk');" ^
  "$sc.TargetPath = '%PROJECT_DIR%\dist\GoGreen Backend.exe';" ^
  "$sc.WorkingDirectory = '%PROJECT_DIR%';" ^
  "$sc.IconLocation = '%PROJECT_DIR%\assets\go_green (2).ico';" ^
  "$sc.Description = 'Go Green Backend Server Manager';" ^
  "$sc.Save()"

IF ERRORLEVEL 1 (
    echo [WARN] Shortcut creation failed.
) ELSE (
    echo [OK] Shortcut created on Desktop.
)

echo.
echo ========================================
echo  Done! Launch from your Desktop icon.
echo ========================================
pause