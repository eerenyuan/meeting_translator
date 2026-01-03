"""
Translation Client Factory
Provides provider-agnostic client instantiation
"""

from typing import Optional, Dict
import os

from translation_client_base import BaseTranslationClient, TranslationProvider
from livetranslate_client import LiveTranslateClient
from livetranslate_text_client import LiveTranslateTextClient
from openai_realtime_client import OpenAIRealtimeClient
from doubao_client import DoubaoClient


class TranslationClientFactory:
    """Factory for creating translation clients based on provider"""

    @staticmethod
    def create_client(
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = None,
        audio_enabled: bool = True,
        glossary_file: Optional[str] = None,
        **kwargs
    ) -> BaseTranslationClient:
        """
        Create a translation client based on provider

        Args:
            provider: Provider name (aliyun, openai, etc.) or None to auto-detect
            api_key: API key for the provider or None to load from env
            source_language: Source language code
            target_language: Target language code
            voice: Voice selection (provider-specific)
            audio_enabled: Whether to enable audio output
            glossary_file: Path to glossary file
            **kwargs: Additional provider-specific parameters

        Returns:
            BaseTranslationClient: Configured translation client

        Raises:
            ValueError: If provider is unsupported or API key is missing
        """

        # Auto-detect provider from environment if not specified
        if provider is None:
            provider = os.getenv("TRANSLATION_PROVIDER", "aliyun").lower()

        provider = provider.lower()

        # Get API key from environment if not provided
        if api_key is None:
            api_key = TranslationClientFactory._get_api_key_for_provider(provider)

        # Get default voice if not specified
        if voice is None:
            voice = TranslationClientFactory._get_default_voice_for_provider(provider)

        # Create client based on provider
        if provider == "aliyun" or provider == "alibaba":
            # Support both "aliyun" and "alibaba" for backward compatibility
            if audio_enabled:
                return LiveTranslateClient(
                    api_key=api_key,
                    source_language=source_language,
                    target_language=target_language,
                    voice=voice,
                    audio_enabled=audio_enabled,
                    glossary_file=glossary_file
                )
            else:
                return LiveTranslateTextClient(
                    api_key=api_key,
                    source_language=source_language,
                    target_language=target_language,
                    glossary_file=glossary_file
                )

        elif provider == "openai":
            return OpenAIRealtimeClient(
                api_key=api_key,
                source_language=source_language,
                target_language=target_language,
                voice=voice,
                audio_enabled=audio_enabled,
                glossary_file=glossary_file,
                **kwargs
            )

        elif provider == "doubao":
            # Doubao requires both app_id and access_token
            access_token = os.getenv("doubao_access_token")
            if not access_token:
                raise ValueError("DOUBAO_ACCESS_TOKEN not found in environment")

            return DoubaoClient(
                api_key=api_key,  # doubao_app_id
                source_language=source_language,
                target_language=target_language,
                voice=voice,
                audio_enabled=audio_enabled,
                glossary_file=glossary_file,
                access_token=access_token,  # doubao_access_token
                **kwargs
            )

        else:
            raise ValueError(
                f"Unsupported provider: {provider}. "
                f"Supported providers: aliyun, openai, doubao"
            )

    @staticmethod
    def _get_api_key_for_provider(provider: str) -> str:
        """Get API key from environment for given provider"""
        key_map = {
            "aliyun": ["DASHSCOPE_API_KEY", "ALIYUN_API_KEY"],
            "alibaba": ["DASHSCOPE_API_KEY", "ALIYUN_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "doubao": ["doubao_app_id", "DOUBAO_APP_ID"],
            "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "deepgram": ["DEEPGRAM_API_KEY"],
            "elevenlabs": ["ELEVENLABS_API_KEY"],
            "cartesia": ["CARTESIA_API_KEY"]
        }

        keys = key_map.get(provider, [])
        for key in keys:
            value = os.getenv(key)
            if value:
                return value

        raise ValueError(
            f"No API key found for provider '{provider}'. "
            f"Please set one of: {', '.join(keys)}"
        )

    @staticmethod
    def _get_default_voice_for_provider(provider: str) -> str:
        """Get default voice for given provider"""
        defaults = {
            "aliyun": "Cherry",
            "alibaba": "Cherry",
            "openai": "alloy",
            "doubao": "default",
            "gemini": "en-US-Neural2-F",
            "elevenlabs": "EXAVITQu4vr4xnSDxMaL"  # Sarah
        }
        return defaults.get(provider, "")

    @staticmethod
    def get_supported_voices(provider: str) -> Dict[str, str]:
        """
        Get supported voices for a provider

        Args:
            provider: Provider name (aliyun, openai, etc.)

        Returns:
            Dict mapping voice IDs to display names
        """
        provider = provider.lower()

        if provider == "aliyun" or provider == "alibaba":
            return {
                "Cherry": "Cherry (Female)",
                "Nofish": "Nofish (Male)",
                "Bella": "Bella (Female)",
                "Alice": "Alice (Female)"
            }
        elif provider == "openai":
            return OpenAIRealtimeClient.get_supported_voices()
        elif provider == "doubao":
            return DoubaoClient.get_supported_voices()
        else:
            return {}

    @staticmethod
    def get_supported_providers() -> Dict[str, str]:
        """
        Get list of supported providers

        Returns:
            Dict mapping provider IDs to display names
        """
        return {
            "aliyun": "Alibaba Cloud (Aliyun)",
            "openai": "OpenAI Realtime API",
            "doubao": "Doubao (ByteDance)"
        }
