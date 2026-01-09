#!/usr/bin/env python3
"""
Meeting Translator - Entry Point
会议翻译工具 - 启动入口

This is a root-level wrapper to launch the application from the repository root.
这是一个根目录层级的包装脚本，用于从仓库根目录启动应用程序。

Usage / 使用方法:
    python main.py              # Direct Python / 直接使用 Python
    uv run main.py              # Using uv (recommended) / 使用 uv（推荐）
    ./run.sh                    # macOS/Linux launcher / macOS/Linux 启动脚本
    run.bat                     # Windows launcher / Windows 启动脚本
"""

import sys
from pathlib import Path

# Add meeting_translator package to Python path
# 将 meeting_translator 包添加到 Python 路径
package_dir = Path(__file__).parent / "meeting_translator"
if package_dir.parent not in sys.path:
    sys.path.insert(0, str(package_dir.parent))

# Import and run main application
# 导入并运行主应用程序
from meeting_translator.main_app import main

if __name__ == "__main__":
    main()
