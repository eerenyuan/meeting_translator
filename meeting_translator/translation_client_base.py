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
        voice: Optional[str] = None,
        audio_enabled: bool = True,
        glossary_file: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize translation client with common parameters

        Args:
            api_key: API key for the translation service
            source_language: Source language code (e.g., "zh", "en")
            target_language: Target language code (e.g., "en", "zh")
            voice: Voice selection (provider-specific, for S2S mode)
            audio_enabled: Whether to enable audio output (True=S2S, False=S2T)
            glossary_file: Path to glossary file for custom terminology
            **kwargs: Additional provider-specific parameters
        """
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.voice = voice
        self.audio_enabled = audio_enabled
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
        Get required input audio sample rate

        Returns:
            Sample rate in Hz (e.g., 16000, 24000)
        """
        pass

    @property
    @abstractmethod
    def output_rate(self) -> int:
        """
        Get output audio sample rate

        Returns:
            Sample rate in Hz (e.g., 24000)
        """
        pass

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        Get supported voices for this provider

        Returns:
            Dict mapping voice IDs to display names
            Example: {"alloy": "Alloy (Neutral)", "echo": "Echo (Male)"}

        Note:
            This method should be overridden by S2S clients.
            S2T clients can return empty dict.
        """
        return {}

    def supports_voice_testing(self) -> bool:
        """
        检查是否支持音色试听功能

        Returns:
            bool: True 如果支持试听功能

        Note:
            Default implementation returns False.
            S2S clients should use AudioPlayerMixin which overrides this.
        """
        return False

    async def test_voice_async(self, text: str = "Hello, this is a test."):
        """
        试听音色（异步）

        生成一段测试音频并播放，让用户测试当前选择的音色效果。

        Args:
            text: 要朗读的测试文本

        Raises:
            NotImplementedError: 如果 provider 不支持试听功能

        Note:
            S2S clients should use AudioPlayerMixin and override this method.
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持音色试听功能")

    def get_translation_mode(self) -> TranslationMode:
        """
        获取当前 client 的翻译模式

        Returns:
            TranslationMode: S2S 或 S2T

        Note:
            根据 audio_enabled 参数判断模式。
            True = S2S (语音到语音)，False = S2T (语音到文本)
        """
        if hasattr(self, 'audio_enabled') and self.audio_enabled:
            return TranslationMode.S2S
        else:
            return TranslationMode.S2T
