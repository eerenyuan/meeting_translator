"""
字幕悬浮窗
可拖动、可缩放的透明字幕显示窗口
支持历史记录和滚动
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizeGrip, QTextEdit, QPushButton
from PyQt5.QtCore import Qt, QPoint, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor
from datetime import datetime
import os

from output_manager import Out
from i18n import get_i18n


class SubtitleWindow(QWidget):
    """字幕悬浮窗"""

    def __init__(self):
        super().__init__()

        # 初始化 i18n
        self.i18n = get_i18n()

        # 窗口属性 - 强制置顶
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |  # 始终在最上层
            Qt.FramelessWindowHint |   # 无边框
            Qt.Tool |                  # 工具窗口（不在任务栏显示）
            Qt.WindowStaysOnTopHint    # 再次确保置顶（某些系统需要）
        )

        # 设置透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 额外确保窗口保持在顶层（macOS 兼容性）
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)

        # 会议记录
        self.meeting_start_time = datetime.now()  # 记录会议开始时间
        self.subtitle_history = []  # 字幕历史记录
        self.current_partial_text = ""  # 当前正在显示的增量文本（未finalize）
        self.current_source_text = ""  # 当前正在显示的源文本（英文）

        # 字体大小设置
        self.font_size = 20  # 默认字体大小
        self.min_font_size = 12  # 最小字体大小
        self.max_font_size = 48  # 最大字体大小

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
        self.subtitle_text.setFont(QFont("Microsoft YaHei", self.font_size, QFont.Bold))  # 使用变量控制的字体大小
        self.subtitle_text.setReadOnly(True)  # 只读
        # 允许文本选择和复制 (类似浏览器行为，但不可编辑)
        self.subtitle_text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.subtitle_text.setStyleSheet("""
            QTextEdit {
                color: #FFFFFF;
                background-color: rgba(20, 20, 25, 220);
                border: 2px solid rgba(100, 150, 255, 100);
                border-radius: 10px;
                padding: 20px;
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
        self.subtitle_text.setPlaceholderText(self.i18n.t("ui.subtitle.waiting"))
        layout.addWidget(self.subtitle_text)

        # 控制栏（右下角）：字体大小按钮 + 缩放手柄
        control_bar = QHBoxLayout()
        control_bar.setSpacing(8)

        # 添加弹性空间，把控件推到右边
        control_bar.addStretch()

        # 字体减小按钮
        self.font_decrease_btn = QPushButton("A-")
        self.font_decrease_btn.setFixedSize(40, 30)
        self.font_decrease_btn.setToolTip(self.i18n.t("ui.tooltips.font_decrease"))
        self.font_decrease_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(100, 150, 255, 150);
                border: 2px solid rgba(255, 255, 255, 180);
                border-radius: 5px;
                color: white;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(120, 170, 255, 200);
            }
            QPushButton:pressed {
                background-color: rgba(80, 130, 235, 180);
            }
        """)
        self.font_decrease_btn.clicked.connect(self.decrease_font_size)
        control_bar.addWidget(self.font_decrease_btn)

        # 字体增大按钮
        self.font_increase_btn = QPushButton("A+")
        self.font_increase_btn.setFixedSize(40, 30)
        self.font_increase_btn.setToolTip(self.i18n.t("ui.tooltips.font_increase"))
        self.font_increase_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(100, 150, 255, 150);
                border: 2px solid rgba(255, 255, 255, 180);
                border-radius: 5px;
                color: white;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(120, 170, 255, 200);
            }
            QPushButton:pressed {
                background-color: rgba(80, 130, 235, 180);
            }
        """)
        self.font_increase_btn.clicked.connect(self.increase_font_size)
        control_bar.addWidget(self.font_increase_btn)

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
        control_bar.addWidget(self.size_grip)

        # 控制栏布局（右下角对齐）
        layout.addLayout(control_bar)

        self.setLayout(layout)

    def update_subtitle(self, source: str, target: str, is_final: bool = True, predicted_text: str = None):
        """
        更新字幕内容

        Args:
            source: 源语言文本
            target: 目标语言文本
            is_final: 是否为最终文本（True=已finalize，False=增量文本）
            predicted_text: 预测文本（Qwen API的stash部分，可选）
        """
        if not target:
            return

        if is_final:
            # 最终文本：添加到历史记录（存储结构化数据）
            timestamp = datetime.now()
            self.subtitle_history.append({
                'timestamp': timestamp,
                'source': source or "",
                'target': target
            })

            # 清空当前增量文本
            self.current_partial_text = ""
            self.current_predicted_text = ""
            self.current_source_text = ""

            # 重新渲染所有内容
            self._render_subtitles()

            # Out.debug(f"字幕已添加: {source} → {target}")
        else:
            # 增量文本：临时显示在最后一行
            self.current_partial_text = target
            self.current_predicted_text = predicted_text or ""  # 保存预测文本
            self.current_source_text = source or ""  # 保存当前源文本
            self._render_subtitles()

            # Out.debug(f"增量字幕: {target}")

    def _render_subtitles(self):
        """渲染所有字幕（历史记录 + 当前增量）"""
        # HTML 格式的文本 - 使用更好的排版样式
        html_parts = []

        # 添加历史记录（白色，已确定）
        for item in self.subtitle_history:
            timestamp_str = item['timestamp'].strftime("%H:%M:%S")
            source = item['source']
            target = item['target']

            # target 的显示格式始终保持一致（不包含箭头）
            target_html = f'{self._escape_html(target)}'

            # 构建头部行：timestamp + (source + 箭头) 或仅 timestamp
            if source:
                # 双语格式：source + 箭头作为 source 的一部分
                header_line = f"[{timestamp_str}] {self._escape_html(source)} 　　　　→"
            else:
                # 单语言格式：只有 timestamp
                header_line = f"[{timestamp_str}]"

            # 复用相同的结构
            html_parts.append(f'''
                <div style="margin-bottom: 12px;">
                    <span>{header_line}</span><span>{target_html}</span>
                    
                </div>
            ''')

        # 如果有增量文本，添加到末尾
        if self.current_partial_text:
            timestamp_str = datetime.now().strftime("%H:%M:%S")

            # target 的显示格式始终保持一致（不包含箭头）
            target_html = f'{self._escape_html(self.current_partial_text)}'
            # 构建头部行：timestamp + (source + 箭头) 或仅 timestamp
            if self.current_source_text:
                # 双语格式：source + 箭头作为 source 的一部分
                header_line = f"[{timestamp_str}] {self._escape_html(self.current_source_text)} 　　　　→"
            else:
                # 单语言格式：只有 timestamp
                header_line = f"[{timestamp_str}]"

            if self.current_predicted_text:
                predicted_str=f'<span style="color: rgba(160, 160, 160, 0.85);">{self._escape_html(self.current_predicted_text)}</span> '
            else: 
                predicted_str=""
            # 复用相同的结构
            html_parts.append(f'''
                <div style="margin-bottom: 12px;">
                    <span>{header_line}</span>
                    <span>{target_html}</span>
                    {predicted_str}
                    <span style="color: rgba(100, 150, 255, 0.8);">...</span>
                </div>
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

    def increase_font_size(self):
        """增大字体大小"""
        if self.font_size < self.max_font_size:
            self.font_size += 2
            self._update_font()
            Out.status(self.i18n.t("status.font_size_changed", size=self.font_size))
        else:
            Out.status(self.i18n.t("status.font_size_max"))

    def decrease_font_size(self):
        """减小字体大小"""
        if self.font_size > self.min_font_size:
            self.font_size -= 2
            self._update_font()
            Out.status(self.i18n.t("status.font_size_changed", size=self.font_size))
        else:
            Out.status(self.i18n.t("status.font_size_min"))

    def _update_font(self):
        """更新字幕文本框的字体"""
        font = QFont("Microsoft YaHei", self.font_size, QFont.Bold)
        self.subtitle_text.setFont(font)

    def clear_subtitle(self):
        """清空字幕"""
        self.subtitle_history.clear()
        self.current_partial_text = ""
        self.current_predicted_text = ""
        self.current_source_text = ""
        self.subtitle_text.clear()
        self.meeting_start_time = datetime.now()  # 重置开始时间
        Out.status(self.i18n.t("status.subtitle_cleared"))

    def save_subtitles(self, save_dir: str = ".") -> str:
        """
        保存字幕到文件

        Args:
            save_dir: 保存目录

        Returns:
            str: 保存的文件路径
        """
        if not self.subtitle_history:
            Out.warning(self.i18n.t("warnings.no_subtitle_to_save"))
            return ""

        # 计算会议时长
        duration = datetime.now() - self.meeting_start_time
        duration_minutes = int(duration.total_seconds() / 60)

        # 生成文件名：会议记录_YYYYMMDD_HHMMSS_XXmin.txt
        filename = f"{self.i18n.t('ui.subtitle.meeting_record')}_{self.meeting_start_time.strftime('%Y%m%d_%H%M%S')}_{duration_minutes}min.txt"
        filepath = os.path.join(save_dir, filename)

        # 写入文件
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"{self.i18n.t('ui.subtitle.meeting_record')}\n")
                f.write(f"{self.i18n.t('ui.subtitle.start_time')} {self.meeting_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{self.i18n.t('ui.subtitle.end_time')} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{self.i18n.t('ui.subtitle.duration')} {duration_minutes} {self.i18n.t('ui.subtitle.minutes')}\n")
                f.write("=" * 50 + "\n\n")

                # 从结构化数据生成文件格式
                for item in self.subtitle_history:
                    timestamp_str = item['timestamp'].strftime("%H:%M:%S")
                    source = item['source']
                    target = item['target']

                    if source:
                        # 双语格式
                        f.write(f"[{timestamp_str}] {source} 　　　　→ {target}\n\n")
                    else:
                        # 单语言格式
                        f.write(f"[{timestamp_str}] {target}\n\n")

            return filepath
        except Exception as e:
            Out.error(self.i18n.t("errors.subtitle_save_failed", error=str(e)))
            return ""

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