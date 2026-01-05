"""
输出处理器
将翻译消息输出到不同目的地：字幕窗口、控制台、日志文件
"""

import logging
from typing import Optional, List
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
from output_manager import BaseHandler, TranslationMessage, MessageType, IncrementalMode

logger = logging.getLogger(__name__)


class SubtitleHandler(BaseHandler, QObject):
    """
    字幕窗口处理器（线程安全）
    使用 Qt 信号机制实现跨线程的 UI 更新
    """

    # 定义信号：线程安全的字幕更新请求
    _update_signal = pyqtSignal(str, str, bool, str)  # (source, target, is_final, predicted)

    def __init__(self, subtitle_window, enabled_types: Optional[List[MessageType]] = None):
        """
        初始化字幕处理器

        Args:
            subtitle_window: 字幕窗口实例（SubtitleWindow对象）
            enabled_types: 启用的消息类型
        """
        BaseHandler.__init__(self, enabled_types=enabled_types or [
            MessageType.TRANSLATION,
            MessageType.PARTIAL_REPLACE,
            MessageType.PARTIAL_APPEND
        ])
        QObject.__init__(self)  # 初始化 QObject

        self.subtitle_window = subtitle_window
        self.current_partial_text = ""  # 当前增量文本（用于REPLACE模式）

        # 连接信号到槽（在主线程中执行 UI 更新）
        self._update_signal.connect(self._safe_update_subtitle)

    def emit(self, message: TranslationMessage):
        """
        输出到字幕窗口（线程安全）

        Args:
            message: 翻译消息
        """
        if message.message_type == MessageType.TRANSLATION:
            # 最终翻译：添加到历史记录
            self._update_signal.emit(
                message.source_text or "",
                message.target_text,
                True,  # is_final
                ""  # predicted_text (最终翻译不需要)
            )
            self.current_partial_text = ""  # 清空增量文本

        elif message.message_type in [MessageType.PARTIAL_REPLACE, MessageType.PARTIAL_APPEND]:
            # 增量文本：临时显示
            if message.incremental_mode == IncrementalMode.REPLACE:
                # 替换模式（Qwen）：直接替换当前内容
                self.current_partial_text = message.target_text
            else:
                # 追加模式：追加到末尾
                self.current_partial_text += message.target_text

            # 发射信号（线程安全）
            self._update_signal.emit(
                message.source_text or "",
                self.current_partial_text,
                False,  # is_final
                message.predicted_text or ""  # 预测文本
            )

    def _safe_update_subtitle(self, source_text: str, target_text: str, is_final: bool, predicted_text: str):
        """
        线程安全的字幕更新（在主线程中执行）

        Args:
            source_text: 源文本
            target_text: 目标文本
            is_final: 是否最终翻译
            predicted_text: 预测文本
        """
        # 这个方法在主线程中执行（通过 Qt 信号/槽机制）
        self.subtitle_window.update_subtitle(
            source_text=source_text,
            target_text=target_text,
            is_final=is_final,
            predicted_text=predicted_text if not is_final else None
        )


class ConsoleHandler(BaseHandler):
    """
    控制台处理器
    输出到终端/控制台
    """

    def __init__(self, enabled_types: Optional[List[MessageType]] = None,
                 show_source: bool = True, show_metadata: bool = False):
        """
        初始化控制台处理器

        Args:
            enabled_types: 启用的消息类型
            show_source: 是否显示源文本
            show_metadata: 是否显示元数据
        """
        # 默认显示所有类型
        default_types = [
            MessageType.TRANSLATION,
            MessageType.STATUS,
            MessageType.ERROR,
            MessageType.WARNING
        ]
        super().__init__(enabled_types=enabled_types or default_types)

        self.show_source = show_source
        self.show_metadata = show_metadata

    def emit(self, message: TranslationMessage):
        """
        输出到控制台

        Args:
            message: 翻译消息
        """
        # 格式化输出
        output = self._format_message(message)
        if output:
            print(output)

    def _format_message(self, message: TranslationMessage) -> str:
        """格式化消息"""
        if message.message_type == MessageType.TRANSLATION:
            # 翻译结果
            provider = message.metadata.get("provider", "").upper()
            mode = message.metadata.get("mode", "")  # LISTEN 或 SPEAK
            source = message.source_text or ""

            # 构建前缀：[QWEN 听] 或 [QWEN 说]
            if mode:
                if mode == "LISTEN":
                    mode_text = "听"
                elif mode == "SPEAK":
                    mode_text = "说"
                else:
                    mode_text = mode
                prefix = f"[{provider} {mode_text}]"
            else:
                prefix = f"[{provider}]"

            # 构建完整消息
            if source:
                return f"{prefix} {source} → {message.target_text}"
            else:
                return f"{prefix} {message.target_text}"

        elif message.message_type in [MessageType.PARTIAL_REPLACE, MessageType.PARTIAL_APPEND]:
            # 增量文本（通常不在控制台显示，除非DEBUG模式）
            return f"[增量] {message.target_text}"

        elif message.message_type == MessageType.STATUS:
            # 状态信息
            return f"[状态] {message.target_text}"

        elif message.message_type == MessageType.ERROR:
            # 错误信息
            return f"[错误] {message.target_text}"

        elif message.message_type == MessageType.WARNING:
            # 警告信息
            return f"[警告] {message.target_text}"

        elif message.message_type == MessageType.USER_ALERT:
            # 用户提示（解析"标题|内容"格式）
            text = message.target_text
            if "|" in text:
                title, content = text.split("|", 1)
                return f"[提示] {title}: {content}"
            else:
                return f"[提示] {text}"

        return message.target_text


class LogFileHandler(BaseHandler):
    """
    日志文件处理器
    将消息写入日志文件（使用Python logging）
    """

    def __init__(self, logger_name: str = __name__,
                 enabled_types: Optional[List[MessageType]] = None):
        """
        初始化日志文件处理器

        Args:
            logger_name: logger名称
            enabled_types: 启用的消息类型
        """
        # 默认记录完整信息（翻译结果 + 技术信息，不包含增量翻译）
        default_types = [
            MessageType.TRANSLATION,  # ✅ 翻译结果（完整记录）
            # ❌ 不包含 PARTIAL_REPLACE/PARTIAL_APPEND - 增量翻译不记录
            MessageType.STATUS,       # ✅ 状态信息
            MessageType.ERROR,        # ✅ 错误
            MessageType.WARNING       # ✅ 警告
            # ❌ 不包含 DEBUG - 调试信息默认不记录
        ]
        super().__init__(enabled_types=enabled_types or default_types)

        self.logger_name = logger_name
        self.logger = logging.getLogger(logger_name)

    def emit(self, message: TranslationMessage):
        """
        写入日志文件

        Args:
            message: 翻译消息
        """
        # 映射MessageType到logging level
        if message.message_type == MessageType.ERROR:
            level = logging.ERROR
        elif message.message_type == MessageType.WARNING:
            level = logging.WARNING
        elif message.message_type == MessageType.DEBUG:
            level = logging.DEBUG
        else:
            level = logging.INFO

        # 格式化日志消息
        log_msg = self._format_log_message(message)

        # 记录日志
        self.logger.log(level, log_msg)

    def _format_log_message(self, message: TranslationMessage) -> str:
        """格式化日志消息"""
        parts = []

        # 添加provider和模式标识
        provider = message.metadata.get("provider", "").upper()
        mode = message.metadata.get("mode", "")  # LISTEN 或 SPEAK

        if provider:
            if mode:
                if mode == "LISTEN":
                    mode_text = "听"
                elif mode == "SPEAK":
                    mode_text = "说"
                else:
                    mode_text = mode
                parts.append(f"[{provider} {mode_text}]")
            else:
                parts.append(f"[{provider}]")

        # 添加源文本
        if message.source_text:
            parts.append(f"{message.source_text} ->")

        # 添加目标文本
        parts.append(message.target_text)

        return " ".join(parts)


class MultiHandler(BaseHandler):
    """
    组合处理器
    将消息同时分发到多个处理器
    """

    def __init__(self, handlers: List[BaseHandler],
                 enabled_types: Optional[List[MessageType]] = None):
        """
        初始化组合处理器

        Args:
            handlers: 子处理器列表
            enabled_types: 启用的消息类型
        """
        super().__init__(enabled_types=enabled_types)
        self.handlers = handlers

    def add_handler(self, handler: BaseHandler):
        """添加子处理器"""
        if handler not in self.handlers:
            self.handlers.append(handler)

    def remove_handler(self, handler: BaseHandler):
        """移除子处理器"""
        if handler in self.handlers:
            self.handlers.remove(handler)

    def emit(self, message: TranslationMessage):
        """分发到所有子处理器"""
        for handler in self.handlers:
            handler.handle(message)


class AlertHandler(BaseHandler, QObject):
    """
    用户提示处理器
    显示 QMessageBox 弹窗，同时支持日志记录
    """

    # 定义信号（线程安全）
    _show_alert_signal = pyqtSignal(str, str)  # (title, message)

    def __init__(self, parent_widget=None, show_dialog=True, enabled_types=None):
        """
        初始化用户提示处理器

        Args:
            parent_widget: 父窗口（QMessageBox 的父对象）
            show_dialog: 是否显示弹窗（测试时可设为 False）
            enabled_types: 启用的消息类型
        """
        # 默认只处理 USER_ALERT
        default_types = [MessageType.USER_ALERT]
        BaseHandler.__init__(self, enabled_types=enabled_types or default_types)
        QObject.__init__(self)

        self.parent_widget = parent_widget
        self.show_dialog = show_dialog

        # 连接信号到槽（在主线程中执行弹窗显示）
        self._show_alert_signal.connect(self._show_alert_dialog)

    def emit(self, message: TranslationMessage):
        """
        显示用户提示（线程安全）

        Args:
            message: 翻译消息
        """
        # 从 target_text 解析标题和内容
        # 格式: "标题|内容" 或纯内容
        text = message.target_text

        if "|" in text:
            title, content = text.split("|", 1)
        else:
            # 如果没有分隔符，使用默认标题
            title = "提示"
            content = text

        # 发射信号（线程安全）
        if self.show_dialog:
            self._show_alert_signal.emit(title, content)

    def _show_alert_dialog(self, title: str, content: str):
        """
        在主线程中显示弹窗

        Args:
            title: 弹窗标题
            content: 弹窗内容
        """
        if not self.show_dialog:
            return  # 静默模式，不显示弹窗

        try:
            # 使用 warning 图标显示提示
            QMessageBox.warning(self.parent_widget, title, content)
        except Exception as e:
            logger.error(f"显示弹窗失败: {e}")


# 测试代码
if __name__ == "__main__":
    from output_manager import OutputManager

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # 创建OutputManager
    manager = OutputManager.get_instance()

    # 添加控制台处理器
    manager.add_handler(ConsoleHandler())

    # 添加日志处理器
    manager.add_handler(LogFileHandler())

    # 测试输出
    print("=== 测试控制台和日志输出 ===\n")

    manager.status("系统启动中...")
    manager.translation("你好世界", source_text="Hello world", metadata={"provider": "openai"})
    manager.partial("你好", mode=IncrementalMode.REPLACE, metadata={"provider": "qwen"})
    manager.error("连接失败")

    print("\n=== 测试源文本为空 ===")
    manager.translation("你好", metadata={"provider": "doubao"})
