"""
Client Output Mixin
提供统一的输出接口给所有 translation clients
"""

from typing import Optional, Dict, Any
from output_manager import Out, MessageType, TranslationMessage


class OutputMixin:
    """
    Translation Client 输出混入类

    为所有 translation clients 提供统一的输出接口，
    确保所有 providers 的输出格式一致。

    使用方法：
        class MyClient(BaseTranslationClient, OutputMixin):
            pass
    """

    def _get_provider_name(self) -> str:
        """获取 provider 名称（用于 metadata）"""
        class_name = self.__class__.__name__
        # 从类名推断 provider
        if "Qwen" in class_name or "Aliyun" in class_name:
            return "ALIYUN"
        elif "Doubao" in class_name:
            return "DOUBAO"
        elif "OpenAI" in class_name:
            return "OPENAI"
        else:
            return "UNKNOWN"

    def _build_metadata(self, extra_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建标准 metadata

        Args:
            extra_metadata: 额外的 metadata

        Returns:
            完整的 metadata dict
        """
        metadata = {
            "provider": self._get_provider_name(),
            "source_language": getattr(self, 'source_language', 'zh'),
            "target_language": getattr(self, 'target_language', 'en'),
            "audio_enabled": getattr(self, 'audio_enabled', True),
        }

        # 添加音色信息（如果有）
        if hasattr(self, 'voice') and self.voice:
            metadata["voice"] = self.voice

        # 合并额外的 metadata
        if extra_metadata:
            metadata.update(extra_metadata)

        return metadata

    def output_translation(
        self,
        target_text: str,
        source_text: Optional[str] = None,
        is_final: bool = True,
        extra_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        输出最终翻译结果

        Args:
            target_text: 翻译后的文本
            source_text: 原文（可选）
            is_final: 是否为最终结果（True=已finalize，False=增量）
            extra_metadata: 额外的 metadata
        """
        metadata = self._build_metadata(extra_metadata)
        metadata["is_final"] = is_final

        if is_final:
            Out.translation(target_text, source_text=source_text, metadata=metadata)
        else:
            # 增量翻译（用于实时显示）
            Out.partial(target_text, mode="replace", source_text=source_text, metadata=metadata)

    def output_status(self, message: str, extra_metadata: Optional[Dict[str, Any]] = None):
        """
        输出状态信息

        Args:
            message: 状态消息
            extra_metadata: 额外的 metadata
        """
        metadata = self._build_metadata(extra_metadata)
        Out.status(message, metadata=metadata)

    def output_error(self, message: str, exc_info: bool = False, extra_metadata: Optional[Dict[str, Any]] = None):
        """
        输出错误信息

        Args:
            message: 错误消息
            exc_info: 是否包含异常堆栈
            extra_metadata: 额外的 metadata
        """
        metadata = self._build_metadata(extra_metadata)
        Out.error(message, exc_info=exc_info, metadata=metadata)

    def output_warning(self, message: str, extra_metadata: Optional[Dict[str, Any]] = None):
        """
        输出警告信息

        Args:
            message: 警告消息
            extra_metadata: 额外的 metadata
        """
        metadata = self._build_metadata(extra_metadata)
        Out.warning(message, metadata=metadata)

    def output_debug(self, message: str, extra_metadata: Optional[Dict[str, Any]] = None):
        """
        输出调试信息

        Args:
            message: 调试消息
            extra_metadata: 额外的 metadata
        """
        metadata = self._build_metadata(extra_metadata)
        # 使用 debug 级别（LogFileHandler 会记录，ConsoleHandler 不会显示）
        Out.debug(message, metadata=metadata)
