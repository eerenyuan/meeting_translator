@echo off
REM Set UTF-8 code page
chcp 65001 >nul 2>nul

echo ========================================
echo Meeting Translator - Starting...
echo ========================================
echo.

REM Check .env file
if not exist ".env" (
    echo [ERROR] .env file not found
    echo.
    echo Please copy .env.example to .env and configure your API Key
    echo   copy .env.example .env
    echo.
    pause
    exit /b 1
)

REM Check UV installation
where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] UV is not installed
    echo.
    echo Please install UV:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    echo Or use pip:
    echo   pip install uv
    echo.
    echo To use the old method:
    echo   .venv\Scripts\activate.bat
    echo   cd meeting_translator
    echo   python main_app.py
    echo.
    pause
    exit /b 1
)

REM Run with UV
echo Starting with UV...
echo.

uv run main.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Program failed to run
    echo ========================================
    echo.
    echo Please check:
    echo 1. .env file is configured
    echo 2. Python version 3.9-3.11
    echo 3. Network connection (first run downloads dependencies)
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Program exited
echo ========================================
pause
