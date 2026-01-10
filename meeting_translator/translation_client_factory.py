"""
Translation Client Factory
Provides provider-agnostic client instantiation
"""

from typing import Optional, Dict
import os

from translation_client_base import BaseTranslationClient, TranslationProvider
from qwen_client import QwenClient
from openai_client import OpenAIClient
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
        audio_queue: Optional[object] = None,
        glossary: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> BaseTranslationClient:
        """
        Create a translation client based on provider

        Args:
            provider: Provider name (aliyun, openai, etc.) or None to auto-detect
            api_key: API key for the provider or None to load from env
            source_language: Source language code
            target_language: Target language code
            voice: Voice selection (provider-specific, only for S2S mode)
            audio_enabled: Whether to enable audio output (S2S vs S2T)
            audio_queue: External audio queue (AudioOutputThread.audio_queue)
            glossary: Glossary dictionary (loaded by main program)
            **kwargs: Additional provider-specific parameters

        Returns:
            BaseTranslationClient: Configured translation client

        Raises:
            ValueError: If provider is unsupported or API key is missing
        """

        # Use default provider if not specified (no longer reads from environment)
        if provider is None:
            provider = "aliyun"

        provider = provider.lower()

        # Get API key from environment if not provided
        if api_key is None:
            api_key = TranslationClientFactory._get_api_key_for_provider(provider)

        # Get default voice if not specified (only for S2S mode)
        if voice is None and audio_enabled:
            voice = TranslationClientFactory._get_default_voice_for_provider(provider)

        # Create client based on provider (unified architecture: one class supports both S2S and S2T)
        if provider == "aliyun" or provider == "alibaba":
            # Support both "aliyun" and "alibaba" for backward compatibility
            # QwenClient: single class supports both S2S and S2T via audio_enabled flag
            return QwenClient(
                api_key=api_key,
                source_language=source_language,
                target_language=target_language,
                voice=voice,
                audio_enabled=audio_enabled,
                audio_queue=audio_queue,  # 传入外部队列
                glossary=glossary  # 传入词汇表
            )

        elif provider == "openai":
            # OpenAIClient: single class supports both S2S and S2T via audio_enabled flag
            return OpenAIClient(
                api_key=api_key,
                source_language=source_language,
                target_language=target_language,
                voice=voice,
                audio_enabled=audio_enabled,
                audio_queue=audio_queue,  # 传入外部队列
                glossary=glossary,  # 传入词汇表
                **kwargs  # OpenAI 需要 model 参数
            )

        elif provider == "doubao":
            # Doubao requires both app_id and access_token
            access_token = os.getenv("doubao_access_token")
            if not access_token:
                raise ValueError("DOUBAO_ACCESS_TOKEN not found in environment")

            # DoubaoClient: no voice parameter (uses voice cloning)
            return DoubaoClient(
                api_key=api_key,  # doubao_app_id
                source_language=source_language,
                target_language=target_language,
                audio_enabled=audio_enabled,
                audio_queue=audio_queue,  # 传入外部队列
                glossary=glossary,  # 传入词汇表
                access_token=access_token  # doubao_access_token
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
            "aliyun": "cherry",  # Qwen uses lowercase
            "alibaba": "cherry",
            "openai": "marin",  # OpenAI recommends marin or cedar
            "doubao": "",  # Doubao doesn't support voice selection (voice cloning)
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
            return QwenClient.get_supported_voices()
        elif provider == "openai":
            return OpenAIClient.get_supported_voices()
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
