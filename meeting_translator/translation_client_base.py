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
            voice: Voice selection (provider-specific)
            audio_enabled: Whether to enable audio output
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
    @abstractmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        Get supported voices for this provider

        Returns:
            Dict mapping voice IDs to display names
            Example: {"alloy": "Alloy (Neutral)", "echo": "Echo (Male)"}
        """
        pass

    def start_audio_player(self):
        """
        Start audio playback thread (if applicable)

        Optional method for providers that need to manage audio playback.
        Default implementation does nothing.
        """
        pass
