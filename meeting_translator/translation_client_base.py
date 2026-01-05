"""
Abstract base classes for translation clients
Provides provider-agnostic interface for real-time translation
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict
from enum import Enum


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


class BaseTranslationClient(ABC):
    """
    Abstract base class for translation clients

    All providers must implement this interface to ensure compatibility
    with the MeetingTranslationService
    """

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        glossary_file: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize translation client with common parameters

        Args:
            api_key: API key for the translation service
            source_language: Source language code (e.g., "zh", "en")
            target_language: Target language code (e.g., "en", "zh")
            glossary_file: Path to glossary file for custom terminology
            **kwargs: Additional provider-specific parameters
                     (e.g., voice, audio_enabled for AudioPlayerMixin)
        """
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.glossary_file = glossary_file
        self.is_connected = False

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

    def get_translation_mode(self) -> TranslationMode:
        """
        获取当前 client 的翻译模式

        Returns:
            TranslationMode: S2S 或 S2T

        Note:
            根据 audio_enabled 属性判断模式（由 AudioPlayerMixin 设置）。
            True = S2S (语音到语音)，False = S2T (语音到文本)
        """
        # audio_enabled 由 AudioPlayerMixin 设置
        # 如果没有混入 AudioPlayerMixin，默认为 S2T
        if getattr(self, 'audio_enabled', False):
            return TranslationMode.S2S
        else:
            return TranslationMode.S2T
