"""
Abstract base classes for translation clients
Provides provider-agnostic interface for real-time translation
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict, Any
from enum import Enum
import queue

# Import mixin for composition
from client_output_mixin import OutputMixin


class TranslationProvider(Enum):
    """Supported translation providers"""
    ALIYUN = "aliyun"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPGRAM_ELEVENLABS = "deepgram_elevenlabs"
    DOUBAO = "doubao"


class TranslationMode(Enum):
    """Translation mode types"""
    S2S = "speech_to_speech"  # Speech-to-Speech: 语音输入 → 翻译 → 语音输出
    S2T = "speech_to_text"    # Speech-to-Text: 语音输入 → 翻译 → 文本输出


class BaseTranslationClient(OutputMixin, ABC):
    """
    Abstract base class for translation clients

    All providers must implement this interface to ensure compatibility
    with the MeetingTranslationService

    Composition:
    - OutputMixin: 提供统一的输出接口
    - ABC: 抽象基类，定义抽象方法
    """

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = None,
        audio_enabled: bool = True,
        audio_queue: Optional[queue.Queue] = None,
        glossary: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        """
        Initialize translation client with common parameters

        Args:
            api_key: API key for the translation service
            source_language: Source language code (e.g., "zh", "en")
            target_language: Target language code (e.g., "en", "zh")
            voice: Voice selection for S2S mode (provider-specific)
            audio_enabled: Whether audio output is enabled (True=S2S, False=S2T)
            audio_queue: External queue for decoded audio data (used by S2S mode)
            glossary: Glossary dictionary for translation (optional)
            **kwargs: Additional provider-specific parameters
        """
        # 调用 OutputMixin 的 __init__
        super().__init__(**kwargs)

        # 音频相关配置
        self.audio_enabled = audio_enabled
        self.voice = voice if audio_enabled else None
        self.audio_queue = audio_queue  # 外部队列，用于向 AudioOutputThread 传递音频

        # 设置基础属性
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.is_connected = False

        # 词汇表（所有 providers 共同需要）
        self.glossary = glossary or {}
        if self.glossary:
            self.output_debug(f"已加载词汇表，包含 {len(self.glossary)} 个术语")

    def _queue_audio(self, audio_data: bytes):
        """
        将解码后的音频数据放入外部队列

        Args:
            audio_data: 解码后的 PCM 音频数据
        """
        if self.audio_enabled and self.audio_queue:
            self.audio_queue.put(audio_data)

    @abstractmethod
    async def connect(self):
        """
        Establish connection to translation service

        Raises:
            Exception: If connection fails
        """
        pass

    @abstractmethod
    async def configure_session(self):
        """
        Configure translation session parameters

        Called after connect() to set up session-specific configuration
        such as languages, voice, VAD settings, etc.
        """
        pass

    @abstractmethod
    async def send_audio_chunk(self, audio_data: bytes):
        """
        Send audio data chunk for translation

        Args:
            audio_data: Raw audio bytes (format depends on provider)
        """
        pass

    @abstractmethod
    async def handle_server_messages(self, on_text_received: Optional[Callable] = None):
        """
        Handle incoming messages from server

        This method should run in a loop, processing incoming events
        from the translation service (transcriptions, translations, audio, etc.)

        Args:
            on_text_received: Optional callback for text updates (source, translation)
        """
        pass

    @abstractmethod
    async def close(self):
        """
        Close connection and cleanup resources

        Should gracefully shut down audio streams, close websocket,
        and clean up any other resources.
        """
        pass

    @property
    @abstractmethod
    def input_rate(self) -> int:
        """
        Get required input audio sample rate (from microphone)

        Returns:
            Sample rate in Hz (e.g., 16000, 24000)
        """
        pass

    @property
    @abstractmethod
    def output_rate(self) -> int:
        """
        Get output audio sample rate (for S2S mode)

        Returns:
            Sample rate in Hz (e.g., 16000, 24000)

        Note:
            Subclass should override this to provide provider-specific rate.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 output_rate property"
        )

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        Get supported voices for this provider

        Returns:
            Dict mapping voice IDs to display names
            Example: {"cherry": "Cherry (女声)", "nofish": "Nofish (男声)"}

        Note:
            Subclass should override this to provide provider-specific voices.
            Default implementation returns empty dict (no voice selection).
        """
        return {}

    def supports_voice_testing(self) -> bool:
        """
        检查是否支持音色试听功能

        默认实现返回 True（子类可以覆盖以添加额外条件检查）

        Returns:
            bool: True 如果支持试听功能
        """
        return True

    async def test_voice_async(self, text: str = "Hello, this is a test."):
        """
        试听音色（异步）

        生成一段测试音频并播放，让用户测试当前选择的音色效果。
        此方法会临时创建 PyAudio 播放器，不需要外部队列。

        Args:
            text: 要朗读的测试文本

        Raises:
            NotImplementedError: 如果子类未实现试听功能
        """
        # 默认实现：暂不支持试听
        raise NotImplementedError(
            f"{self.__class__.__name__} 暂不支持音色试听功能"
        )

    def get_translation_mode(self) -> TranslationMode:
        """
        获取当前 client 的翻译模式

        Returns:
            TranslationMode: S2S 或 S2T

        Note:
            根据 audio_enabled 属性判断模式。
            True = S2S (语音到语音)，False = S2T (语音到文本)
        """
        if self.audio_enabled:
            return TranslationMode.S2S
        else:
            return TranslationMode.S2T
