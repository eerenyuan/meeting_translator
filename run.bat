@echo off
chcp 65001 >nul
echo ========================================
echo 会议翻译工具 - 启动中...
echo Meeting Translator - Starting...
echo ========================================
echo.

REM 检查 .env 文件是否存在
if not exist ".env" (
    echo [错误] 未找到 .env 配置文件
    echo [Error] .env configuration file not found
    echo.
    echo 请复制 .env.example 为 .env 并填入你的 API Key
    echo Please copy .env.example to .env and fill in your API Key
    echo.
    echo 示例 / Example:
    echo   copy .env.example .env
    echo   REM 然后编辑 .env 文件 / Then edit .env file
    echo.
    pause
    exit /b 1
)

REM 检查 uv 是否安装
where uv >nul 2>nul
if errorlevel 1 (
    echo [错误] 未安装 uv
    echo [Error] uv is not installed
    echo.
    echo 请安装 uv / Please install uv:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    echo 或使用 pip / Or use pip:
    echo   pip install uv
    echo.
    echo 如果要使用旧方法，请运行 / To use the old method, run:
    echo   .venv\Scripts\activate.bat
    echo   cd meeting_translator
    echo   python main_app.py
    echo.
    pause
    exit /b 1
)

REM 使用 uv 运行程序（自动管理依赖和环境）
echo 使用 uv 启动 (自动管理 Python 环境)...
echo Starting with uv (automatic Python environment management)...
echo.

uv run main.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo 错误：程序运行失败
    echo Error: Program failed to run
    echo ========================================
    echo.
    echo 请检查:
    echo Please check:
    echo 1. 是否已配置 .env 文件
    echo    .env file configured
    echo 2. Python 版本是否为 3.9-3.11
    echo    Python version is 3.9-3.11
    echo 3. 网络连接是否正常（首次运行需要下载依赖）
    echo    Network connection is available (first run downloads dependencies)
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo 程序已退出
echo Program exited
echo ========================================
pause
