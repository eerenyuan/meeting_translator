"""
字幕悬浮窗
可拖动、可缩放的透明字幕显示窗口
支持历史记录和滚动
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizeGrip, QTextEdit
from PyQt5.QtCore import Qt, QPoint, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor
from datetime import datetime
import os

from output_manager import Out


class SubtitleWindow(QWidget):
    """字幕悬浮窗"""

    def __init__(self):
        super().__init__()

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |  # 始终在最上层
            Qt.FramelessWindowHint |   # 无边框
            Qt.Tool                     # 工具窗口（不在任务栏显示）
        )

        # 设置透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 会议记录
        self.meeting_start_time = datetime.now()  # 记录会议开始时间
        self.subtitle_history = []  # 字幕历史记录
        self.current_partial_text = ""  # 当前正在显示的增量文本（未finalize）

        # 初始化 UI
        self.init_ui()

        # 拖动相关
        self.drag_position = None

        # 设置初始大小和位置
        self.resize(1200, 400)  # 增大初始尺寸：1200x400
        self.setMinimumSize(400, 200)  # 设置最小尺寸，避免太小
        self.move(100, 100)

    def init_ui(self):
        """初始化 UI"""
        # 主布局
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # 字幕文本框（支持滚动和历史记录）
        self.subtitle_text = QTextEdit()
        self.subtitle_text.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        self.subtitle_text.setReadOnly(True)  # 只读
        self.subtitle_text.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁用文本交互，允许窗口拖动
        self.subtitle_text.setStyleSheet("""
            QTextEdit {
                color: #FFFFFF;
                background-color: rgba(0, 0, 0, 200);
                border: none;
                border-radius: 8px;
                padding: 15px;
            }
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 30);
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(100, 150, 255, 150);
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(120, 170, 255, 200);
            }
        """)
        self.subtitle_text.setPlaceholderText("等待翻译...")
        layout.addWidget(self.subtitle_text)

        # 添加缩放手柄（更大、更明显）
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(30, 30)  # 增大手柄 20x20 -> 30x30
        self.size_grip.setStyleSheet("""
            QSizeGrip {
                background-color: rgba(100, 150, 255, 150);
                border: 2px solid rgba(255, 255, 255, 180);
                border-radius: 5px;
            }
            QSizeGrip:hover {
                background-color: rgba(120, 170, 255, 200);
            }
        """)

        # 手柄布局（右下角）
        layout.addWidget(self.size_grip, 0, Qt.AlignRight | Qt.AlignBottom)

        self.setLayout(layout)

    def update_subtitle(self, source_text: str, target_text: str, is_final: bool = True,predicted_text: str = None):
        """
        更新字幕内容

        Args:
            source_text: 源语言文本（英文）
            target_text: 目标语言文本（中文）
            is_final: 是否为最终文本（True=已finalize，False=增量文本）
            predicted_text: 预测文本（Qwen API的stash部分，可选）
        """
        if not target_text:
            return

        if is_final:
            # 最终文本：添加到历史记录
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_text = f"[{timestamp}] {target_text}"
            self.subtitle_history.append(formatted_text)

            # 清空当前增量文本
            self.current_partial_text = ""
            self.current_predicted_text = ""

            # 重新渲染所有内容
            self._render_subtitles()

            Out.debug(f"字幕已添加: {target_text}")
        else:
            # 增量文本：临时显示在最后一行
            self.current_partial_text = target_text
            self.current_predicted_text = predicted_text or ""  # 保存预测文本
            self._render_subtitles()

            Out.debug(f"增量字幕: {target_text}")

    def _render_subtitles(self):
        """渲染所有字幕（历史记录 + 当前增量）"""
        # HTML 格式的文本
        html_parts = []

        # 添加历史记录（白色，已确定）
        for line in self.subtitle_history:
            html_parts.append(f'<p style="color: white; margin: 5px 0;">{self._escape_html(line)}</p>')

        # 如果有增量文本，添加到末尾
        if self.current_partial_text:
            timestamp = datetime.now().strftime("%H:%M:%S")

            if self.current_predicted_text:
                # 有预测部分：已确定文本（深色）+ 预测文本（浅色）
                html_parts.append(f'''
                    <p style="color: rgba(255, 255, 255, 0.95); margin: 5px 0;">
                        [{timestamp}] {self._escape_html(self.current_partial_text)}<span style="color: rgba(160, 160, 160, 0.85);">{self._escape_html(self.current_predicted_text)}</span> <span style="color: rgba(100, 150, 255, 0.8);">...</span>
                    </p>
                ''')
            else:
                # 没有预测部分，只有已确定文本
                html_parts.append(f'''
                    <p style="color: rgba(255, 255, 255, 0.9); margin: 5px 0;">
                        [{timestamp}] {self._escape_html(self.current_partial_text)} <span style="color: rgba(100, 150, 255, 0.8);">...</span>
                    </p>
                ''')

        # 组合所有 HTML
        html_content = ''.join(html_parts)

        # 更新文本框（使用 HTML）
        self.subtitle_text.setHtml(html_content)

        # 自动滚动到底部
        cursor = self.subtitle_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.subtitle_text.setTextCursor(cursor)
        self.subtitle_text.ensureCursorVisible()

    def _escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

    def clear_subtitle(self):
        """清空字幕"""
        self.subtitle_history.clear()
        self.current_partial_text = ""
        self.current_predicted_text = ""
        self.subtitle_text.clear()
        self.meeting_start_time = datetime.now()  # 重置开始时间
        Out.status("字幕已清空")

    def save_subtitles(self, save_dir: str = ".") -> str:
        """
        保存字幕到文件

        Args:
            save_dir: 保存目录

        Returns:
            str: 保存的文件路径
        """
        if not self.subtitle_history:
            Out.warning("没有字幕内容可保存")
            return ""

        # 计算会议时长
        duration = datetime.now() - self.meeting_start_time
        duration_minutes = int(duration.total_seconds() / 60)

        # 生成文件名：会议记录_YYYYMMDD_HHMMSS_XXmin.txt
        filename = f"会议记录_{self.meeting_start_time.strftime('%Y%m%d_%H%M%S')}_{duration_minutes}min.txt"
        filepath = os.path.join(save_dir, filename)

        # 写入文件
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"会议记录\n")
                f.write(f"开始时间: {self.meeting_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"会议时长: {duration_minutes} 分钟\n")
                f.write("=" * 50 + "\n\n")

                for line in self.subtitle_history:
                    f.write(line + "\n\n")

            Out.status(f"字幕已保存到: {filepath}")
            return filepath
        except Exception as e:
            Out.error(f"保存字幕失败: {e}")
            return ""

    def get_subtitle_content(self) -> str:
        """
        获取所有字幕内容（用于外部保存）

        Returns:
            str: 字幕内容
        """
        return "\n\n".join(self.subtitle_history)

    # 拖动功能
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            # 记录拖动起始位置
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if event.buttons() == Qt.LeftButton and self.drag_position:
            # 移动窗口
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self.drag_position = None

    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件（清空字幕）"""
        if event.button() == Qt.LeftButton:
            self.clear_subtitle()
            event.accept()


# 测试代码
if __name__ == "__main__":
    import sys
    import os

    # Fix Qt plugin path for Windows
    if sys.platform == 'win32':
        import PyQt5 as _PyQt5
        pyqt5_dir = os.path.dirname(_PyQt5.__file__)
        qt_plugin_path = os.path.join(pyqt5_dir, 'Qt5', 'plugins')
        os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(qt_plugin_path, 'platforms')

    from PyQt5.QtWidgets import QApplication
    import time

    app = QApplication(sys.argv)

    # 创建字幕窗口
    subtitle_window = SubtitleWindow()
    subtitle_window.show()

    # 模拟更新字幕
    def test_update():
        import random
        english_samples = [
            "Hello, how are you today?",
            "The meeting will start in 5 minutes.",
            "Can you hear me clearly?",
            "Let's discuss the project timeline."
        ]
        chinese_samples = [
            "你好，今天怎么样？",
            "会议将在5分钟后开始。",
            "你能清楚地听到我说话吗？",
            "让我们讨论一下项目时间表。"
        ]

        for i in range(len(english_samples)):
            subtitle_window.update_subtitle(
                english_samples[i],
                chinese_samples[i]
            )
            QApplication.processEvents()
            time.sleep(3)

    # 在单独线程中测试
    import threading
    test_thread = threading.Thread(target=test_update, daemon=True)
    test_thread.start()

    sys.exit(app.exec_())
