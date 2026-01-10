"""
统一输出管理器
管理所有翻译输出到不同目的地（字幕窗口、控制台、日志文件）
支持渐进式迁移，新旧系统可以共存
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import logging
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型（类似LogLevel）"""

    # 翻译相关
    SUBTITLE = "subtitle"            # S2T 字幕翻译（显示在字幕窗口 + log + console）
    TRANSLATION = "translation"      # S2S 翻译（只输出到 log + console，不显示字幕）

    # 状态相关
    STATUS = "status"                # 状态信息（连接、断开、启动、停止等）
    ERROR = "error"                  # 错误信息
    WARNING = "warning"              # 警告信息

    # 用户相关
    USER_ALERT = "user_alert"        # 用户提示/弹窗（QMessageBox）

    # 调试相关
    DEBUG = "debug"                  # 调试信息（默认不显示）


class IncrementalMode(Enum):
    """增量文本更新模式"""
    APPEND = "append"    # 追加：新文本追加到末尾
    REPLACE = "replace"  # 替换：新文本替换当前内容（Qwen API）


@dataclass
class TranslationMessage:
    """
    翻译消息数据模型
    支持可选的源文本、增量更新、元数据、预测文本
    """
    message_type: MessageType
    target_text: str                       # 目标文本（必填）
    source_text: Optional[str] = None      # 源文本（可选，很多API不提供）
    predicted_text: Optional[str] = None   # 预测文本（Qwen API的stash字段）
    incremental_mode: Optional[IncrementalMode] = None  # 增量模式
    is_final: bool = True                  # 是否为最终结果（False=增量）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)

    # 会话信息（用于关联同一句话的增量更新）
    session_id: Optional[str] = None       # 会话ID
    sequence_id: Optional[str] = None      # 序列ID（用于关联增量更新）

    def __post_init__(self):
        """后处理：根据is_final自动推断incremental_mode"""
        if not self.is_final and self.incremental_mode is None:
            # 默认使用REPLACE模式（Qwen风格）
            self.incremental_mode = IncrementalMode.REPLACE

    @property
    def has_predicted_text(self) -> bool:
        """是否有预测文本（用于Qwen API）"""
        return bool(self.predicted_text)


class BaseFormatter:
    """格式化器基类"""

    def format(self, message: TranslationMessage) -> str:
        """
        格式化消息

        Args:
            message: 翻译消息

        Returns:
            格式化后的字符串
        """
        raise NotImplementedError


class BaseHandler:
    """
    输出处理器基类

    每个处理器负责将消息输出到一个特定目的地（字幕窗口、控制台、日志等）
    """

    def __init__(self, formatter: BaseFormatter = None,
                 enabled_types: Optional[List[MessageType]] = None):
        """
        初始化处理器

        Args:
            formatter: 格式化器（可选）
            enabled_types: 启用的消息类型列表（None=全部启用）
        """
        self.formatter = formatter or BaseFormatter()
        self.enabled_types = set(enabled_types) if enabled_types else None

    def should_handle(self, message_type: MessageType) -> bool:
        """
        判断是否应该处理此类型的消息

        Args:
            message_type: 消息类型

        Returns:
            True=处理，False=跳过
        """
        if self.enabled_types is None:
            return True  # 全部启用
        return message_type in self.enabled_types

    def handle(self, message: TranslationMessage):
        """
        处理消息（模板方法）

        Args:
            message: 翻译消息
        """
        if not self.should_handle(message.message_type):
            return

        try:
            self.emit(message)
        except Exception as e:
            logger.error(f"Handler {self.__class__.__name__} 处理消息失败: {e}")

    def emit(self, message: TranslationMessage):
        """
        实际输出消息（子类实现）

        Args:
            message: 翻译消息
        """
        raise NotImplementedError


class OutputManager:
    """
    统一输出管理器（单例模式）

    负责将翻译消息分发到所有注册的处理器
    支持渐进式迁移：可以与旧代码共存
    """

    _instance = None

    def __init__(self):
        if OutputManager._instance is not None:
            raise RuntimeError("Use get_instance() to get OutputManager")

        self.handlers: List[BaseHandler] = []
        self.enabled = True  # 全局开关

        # 添加临时的控制台处理器（显示所有消息）
        # 这确保在 _init_output_manager() 调用之前，Out.xxx() 调用也能输出
        # 后续 _init_output_manager() 会清空并替换为完整的配置
        try:
            from output_handlers import ConsoleHandler
            temp_console = ConsoleHandler()  # 默认显示所有类型
            self.add_handler(temp_console)
        except Exception as e:
            # 如果导入失败，至少不会崩溃
            logger.warning(f"无法添加临时 ConsoleHandler: {e}")

    @classmethod
    def get_instance(cls) -> 'OutputManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_handler(self, handler: BaseHandler):
        """
        添加输出处理器

        Args:
            handler: 输出处理器
        """
        if handler not in self.handlers:
            self.handlers.append(handler)
            logger.debug(f"添加处理器: {handler.__class__.__name__}")

    def remove_handler(self, handler: BaseHandler):
        """
        移除输出处理器

        Args:
            handler: 输出处理器
        """
        if handler in self.handlers:
            self.handlers.remove(handler)
            logger.debug(f"移除处理器: {handler.__class__.__name__}")

    def emit(self, message: TranslationMessage):
        """
        发送消息到所有处理器

        Args:
            message: 翻译消息
        """
        if not self.enabled:
            return

        for handler in self.handlers:
            try:
                handler.handle(message)
            except Exception as e:
                logger.error(f"分发消息到 {handler.__class__.__name__} 失败: {e}")

    # ========== 便捷方法 ==========

    def translation(self, target_text: str, source_text: Optional[str] = None,
                   metadata: Dict[str, Any] = None):
        """
        发送最终翻译结果（S2S 模式或通用翻译）

        Args:
            target_text: 目标文本
            source_text: 源文本（可选）
            metadata: 元数据
        """
        message = TranslationMessage(
            message_type=MessageType.TRANSLATION,
            target_text=target_text,
            source_text=source_text,
            is_final=True,
            metadata=metadata or {}
        )
        self.emit(message)

    def subtitle(self, target_text: str, source_text: Optional[str] = None,
                 is_final: bool = True, predicted_text: Optional[str] = None,
                 metadata: Dict[str, Any] = None):
        """
        发送字幕翻译结果（S2T 模式）

        字幕会显示在字幕窗口、控制台和日志文件中。

        Args:
            target_text: 目标文本（字幕内容）
            source_text: 源文本（可选）
            is_final: 是否为最终字幕（False=临时字幕，可被替换；True=最终字幕，换行显示）
            predicted_text: 预测文本（Qwen API 的 stash 字段，可选）
            metadata: 元数据
        """
        # 处理 metadata，从中提取 predicted_text（如果存在）
        final_metadata = metadata or {}
        final_predicted = predicted_text or final_metadata.pop('predicted_text', None)

        message = TranslationMessage(
            message_type=MessageType.SUBTITLE,
            target_text=target_text,
            source_text=source_text,
            is_final=is_final,
            predicted_text=final_predicted,
            metadata=final_metadata
        )
        self.emit(message)

    def status(self, message: str, metadata: Dict[str, Any] = None):
        """
        发送状态信息

        Args:
            message: 状态消息
            metadata: 元数据
        """
        msg = TranslationMessage(
            message_type=MessageType.STATUS,
            target_text=message,
            metadata=metadata or {}
        )
        self.emit(msg)

    def error(self, message: str, exc_info=False, metadata: Dict[str, Any] = None):
        """
        发送错误信息

        Args:
            message: 错误消息
            exc_info: 是否包含异常堆栈信息（True=包含，会附加到message后）
            metadata: 元数据
        """
        import traceback

        final_message = message
        if exc_info:
            # 附加堆栈信息
            exc_info_data = (metadata.get('exc_info') if metadata else None) or sys.exc_info()
            traceback_str = ''.join(traceback.format_exception(*exc_info_data))
            if traceback_str:
                final_message = f"{message}\n{traceback_str}"

        msg = TranslationMessage(
            message_type=MessageType.ERROR,
            target_text=final_message,
            metadata=metadata or {}
        )
        self.emit(msg)

    def warning(self, message: str, metadata: Dict[str, Any] = None):
        """
        发送警告信息

        Args:
            message: 警告消息
            metadata: 元数据
        """
        msg = TranslationMessage(
            message_type=MessageType.WARNING,
            target_text=message,
            metadata=metadata or {}
        )
        self.emit(msg)

    def debug(self, message: str, metadata: Dict[str, Any] = None):
        """
        发送调试信息

        Args:
            message: 调试消息
            metadata: 元数据
        """
        msg = TranslationMessage(
            message_type=MessageType.DEBUG,
            target_text=message,
            metadata=metadata or {}
        )
        self.emit(msg)

    def user_alert(self, message: str, title: str = "提示",
                   metadata: Dict[str, Any] = None):
        """
        显示用户提示（弹窗 + 日志 + 控制台）

        Args:
            message: 提示内容
            title: 弹窗标题（默认 "提示"）
            metadata: 元数据
        """
        msg = TranslationMessage(
            message_type=MessageType.USER_ALERT,
            target_text=f"{title}|{message}",
            metadata=metadata or {}
        )
        self.emit(msg)


# 全局便捷函数
def get_output_manager() -> OutputManager:
    """获取OutputManager单例"""
    return OutputManager.get_instance()


# ========== 模块级单例 ==========
# 提供简洁的全局访问点
# 使用示例：
#   from output_manager import Out
#   Out.error("启动失败", exc_info=True)
#   Out.translation("你好", source_text="Hello")
Out = OutputManager.get_instance()


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # 测试基本功能
    manager = OutputManager.get_instance()

    # 创建测试handler
    class TestHandler(BaseHandler):
        def emit(self, message: TranslationMessage):
            print(f"[{message.message_type.value}] {message.target_text}")

    manager.add_handler(TestHandler())

    # 测试各种消息类型
    print("=== 测试输出管理器 ===")

    manager.status("系统启动")
    manager.translation("你好世界", source_text="Hello world")
    manager.partial("你好", mode=IncrementalMode.REPLACE)
    manager.error("连接失败")

    print("\n=== 测试源文本为空 ===")
    manager.translation("你好")  # source_text=None

    print("\n=== 测试元数据 ===")
    manager.translation("你好", metadata={"provider": "qwen", "confidence": 0.95})
