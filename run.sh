#!/usr/bin/env bash
# Meeting Translator Launcher for macOS/Linux
# 会议翻译工具启动脚本 (macOS/Linux)
set -e

echo "========================================"
echo "会议翻译工具 - 启动中..."
echo "Meeting Translator - Starting..."
echo "========================================"
echo

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[错误] 未找到 .env 配置文件"
    echo "[Error] .env configuration file not found"
    echo
    echo "请复制 .env.example 为 .env 并填入你的 API Key"
    echo "Please copy .env.example to .env and fill in your API Key"
    echo
    echo "示例 / Example:"
    echo "  cp .env.example .env"
    echo "  # 然后编辑 .env 文件 / Then edit .env file"
    echo
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "[错误] 未安装 uv"
    echo "[Error] uv is not installed"
    echo
    echo "请安装 uv / Please install uv:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo
    echo "或使用 pip / Or use pip:"
    echo "  pip install uv"
    echo
    exit 1
fi

# Run with uv (auto-installs dependencies if needed)
echo "使用 uv 启动 (自动管理 Python 环境)..."
echo "Starting with uv (automatic Python environment management)..."
echo

uv run main.py

echo
echo "========================================"
echo "程序已退出"
echo "Program exited"
echo "========================================"
