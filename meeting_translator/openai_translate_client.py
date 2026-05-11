"""
OpenAI Realtime Translate Client
Implements real-time speech-to-speech and speech-to-text translation
using OpenAI's dedicated translation endpoint (gpt-realtime-translate)

Architecture:
- Dedicated endpoint: wss://api.openai.com/v1/realtime/translations
- Continuous streaming: no response.create needed, audio flows continuously
- Simultaneous output: translated audio + translated transcript + source transcript
- 57 target languages supported (auto-detects source language)
- 24kHz PCM16 input/output
"""

import os
import base64
import asyncio
import json
import time
from typing import Dict, Optional
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio

import websockets

from translation_client_base import BaseTranslationClient, TranslationProvider
from output_manager import Out

try:
    from python_socks.async_.asyncio import Proxy
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False


class OpenAITranslateClient(BaseTranslationClient):
    """
    OpenAI Realtime Translate Client

    Uses gpt-realtime-translate model on dedicated translation endpoint.
    Both S2S and S2T are handled by the same session:
    - session.output_audio.delta -> translated audio (S2S)
    - session.output_transcript.delta -> translated text (S2T)
    - session.input_transcript.delta -> source language text (ASR)

    Key differences from OpenAI Realtime conversation API:
    - Endpoint: /v1/realtime/translations (not /v1/realtime)
    - Continuous mode: no response.create, just keep appending audio
    - No conversation lifecycle, no turn management
    """

    provider = TranslationProvider.OPENAI_TRANSLATE

    AUDIO_RATE = 24000

    SUPPORTED_LANGUAGES = {
        "南非荷兰语": "af",
        "阿拉伯语": "ar",
        "阿塞拜疆语": "az",
        "白俄罗斯语": "be",
        "保加利亚语": "bg",
        "波斯尼亚语": "bs",
        "加泰罗尼亚语": "ca",
        "捷克语": "cs",
        "威尔士语": "cy",
        "丹麦语": "da",
        "德语": "de",
        "希腊语": "el",
        "英语": "en",
        "西班牙语": "es",
        "爱沙尼亚语": "et",
        "波斯语": "fa",
        "芬兰语": "fi",
        "法语": "fr",
        "加利西亚语": "gl",
        "希伯来语": "he",
        "印地语": "hi",
        "克罗地亚语": "hr",
        "匈牙利语": "hu",
        "亚美尼亚语": "hy",
        "印尼语": "id",
        "冰岛语": "is",
        "意大利语": "it",
        "意第绪语": "iw",
        "日语": "ja",
        "哈萨克语": "kk",
        "卡纳达语": "kn",
        "韩语": "ko",
        "立陶宛语": "lt",
        "拉脱维亚语": "lv",
        "毛利语": "mi",
        "马其顿语": "mk",
        "马拉地语": "mr",
        "马来语": "ms",
        "尼泊尔语": "ne",
        "荷兰语": "nl",
        "挪威语": "no",
        "波兰语": "pl",
        "葡萄牙语": "pt",
        "罗马尼亚语": "ro",
        "俄语": "ru",
        "斯洛伐克语": "sk",
        "斯洛文尼亚语": "sl",
        "塞尔维亚语": "sr",
        "瑞典语": "sv",
        "斯瓦希里语": "sw",
        "泰米尔语": "ta",
        "泰语": "th",
        "他加禄语": "tl",
        "土耳其语": "tr",
        "乌克兰语": "uk",
        "乌尔都语": "ur",
        "越南语": "vi",
        "中文": "zh",
    }

    SUPPORTED_VOICES = {}

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = None,
        audio_enabled: bool = True,
        **kwargs
    ):
        if not api_key:
            raise ValueError("API key cannot be empty.")

        self.ws = None

        self._input_rate = self.AUDIO_RATE
        self._input_chunk = 2400
        self._input_format = pyaudio.paInt16
        self._input_channels = 1

        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            **kwargs
        )

        self._source_transcript = ""
        self._target_transcript = ""
        self._last_output_time = 0.0

    @property
    def input_rate(self) -> int:
        return self._input_rate

    @property
    def output_rate(self) -> int:
        return self.AUDIO_RATE

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        return cls.SUPPORTED_VOICES.copy()

    @classmethod
    def get_supported_voices_i18n(cls, i18n) -> Dict[str, str]:
        return cls.SUPPORTED_VOICES.copy()

    @classmethod
    def get_supported_languages(cls) -> Dict[str, str]:
        return cls.SUPPORTED_LANGUAGES.copy()

    async def connect(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Safety-Identifier": "meeting-translator-user",
        }

        ws_url = "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate"

        try:
            proxy_url = (os.getenv("HTTP_PROXY") or
                        os.getenv("http_proxy") or
                        os.getenv("GLOBAL_AGENT_HTTP_PROXY"))

            if PROXY_AVAILABLE and proxy_url:
                self.output_debug(f"Using proxy: {proxy_url}")
                try:
                    proxy = Proxy.from_url(proxy_url)
                    sock = await proxy.connect(
                        dest_host="api.openai.com",
                        dest_port=443,
                        timeout=10
                    )
                    self.ws = await websockets.connect(
                        ws_url,
                        extra_headers=headers,
                        sock=sock,
                        server_hostname="api.openai.com"
                    )
                except Exception as proxy_error:
                    self.output_warning(f"Proxy failed: {proxy_error}, trying direct...")
                    self.ws = await websockets.connect(
                        ws_url,
                        extra_headers=headers
                    )
            else:
                self.ws = await websockets.connect(
                    ws_url,
                    extra_headers=headers
                )

            self.is_connected = True
            mode = "S2S" if self.audio_enabled else "S2T"
            self.output_status(f"Connected to OpenAI Translate API ({mode})")

            await self.configure_session()

        except Exception as e:
            self.output_error(f"Connection failed: {e}", exc_info=True)
            self.is_connected = False
            raise

    async def configure_session(self):
        if not self.is_connected or not self.ws:
            return

        config = {
            "type": "session.update",
            "session": {
                "audio": {
                    "output": {
                        "language": self.target_language,
                    },
                },
            },
        }

        await self.ws.send(json.dumps(config))
        mode = "S2S" if self.audio_enabled else "S2T"
        self.output_status(f"Session configured: target={self.target_language}, mode={mode}")

    async def send_audio_chunk(self, audio_data: bytes):
        if not self.is_connected or not self.ws:
            return

        try:
            event = {
                "type": "session.input_audio_buffer.append",
                "audio": base64.b64encode(audio_data).decode()
            }
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.output_error(f"Send audio failed: {e}")
            self.is_connected = False

    async def handle_server_messages(self, on_text_received=None):
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    event_type = event.get("type", "")

                    if event_type == "session.created":
                        pass

                    elif event_type == "session.updated":
                        self.output_debug("Session updated")

                    elif event_type == "session.input_transcript.delta":
                        delta = event.get("delta", "")
                        if delta:
                            self._source_transcript += delta

                    elif event_type == "session.output_transcript.delta":
                        delta = event.get("delta", "")
                        if delta:
                            self._target_transcript += delta
                            self.output_subtitle(
                                target_text=self._target_transcript,
                                source_text=self._source_transcript if self._source_transcript else None,
                                is_final=False,
                                extra_metadata={
                                    "provider": "openai_translate",
                                    "mode": "S2T" if not self.audio_enabled else "S2S+text",
                                    "stage": "delta"
                                }
                            )

                    elif event_type == "session.output_audio.delta" and self.audio_enabled:
                        audio_b64 = event.get("delta", "")
                        if audio_b64:
                            audio_data = base64.b64decode(audio_b64)
                            self._queue_audio(audio_data)

                    elif event_type == "error":
                        error = event.get("error", {})
                        error_code = error.get("code", "Unknown")
                        error_msg = error.get("message", "Unknown error")
                        self.output_error(f"{error_code}: {error_msg}")

                        if "connection" in error_code.lower() or "unauthorized" in error_code.lower():
                            self.is_connected = False
                            break

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    self.output_warning(f"Event processing error: {e}")
                    continue

        except websockets.exceptions.ConnectionClosed:
            self.output_warning("WebSocket connection closed")
            self.is_connected = False
        except Exception as e:
            self.output_error(f"Message handler error: {e}", exc_info=True)
            self.is_connected = False

    async def close(self):
        self.is_connected = False

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            finally:
                self.ws = None

    def generate_sample_file(
        self,
        input_wav_path: str,
        output_wav_path: str
    ) -> str:
        from pathlib import Path

        input_path = Path(input_wav_path)
        output_path = Path(output_wav_path)

        if not input_path.exists():
            return ""

        if output_path.exists():
            return str(output_path)

        async def _generate():
            try:
                original_audio_enabled = self.audio_enabled
                self.audio_enabled = True

                await asyncio.wait_for(self.connect(), timeout=10.0)

                with open(input_path, 'rb') as f:
                    f.seek(44)
                    audio_data = f.read()

                audio_chunks = []

                async def collect_messages():
                    nonlocal audio_chunks
                    try:
                        async for message in self.ws:
                            try:
                                event = json.loads(message)
                                event_type = event.get("type", "")

                                if event_type == "session.output_audio.delta":
                                    audio_b64 = event.get("delta", "")
                                    if audio_b64:
                                        chunk_data = base64.b64decode(audio_b64)
                                        audio_chunks.append(chunk_data)

                                elif event_type == "error":
                                    break

                            except json.JSONDecodeError:
                                continue
                            except Exception:
                                continue

                            if len(audio_chunks) > 0 and len(audio_chunks) % 50 == 0:
                                elapsed = time.time() - start_time
                                if elapsed > 30:
                                    break

                    except Exception:
                        pass

                message_task = asyncio.create_task(collect_messages())
                start_time = time.time()
                await asyncio.sleep(0.5)

                chunk_size = 100 * 1024
                chunk_count = 0
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i + chunk_size]
                    await self.send_audio_chunk(chunk)
                    chunk_count += 1
                    if chunk_count % 3 == 0 and i + chunk_size < len(audio_data):
                        await asyncio.sleep(0.1)

                import struct
                silence_duration = 2.0
                silence_samples = int(self.output_rate * silence_duration)
                silence_data = struct.pack('<' + 'h' * silence_samples, *[0] * silence_samples)

                for i in range(0, len(silence_data), chunk_size):
                    chunk = silence_data[i:i + chunk_size]
                    await self.send_audio_chunk(chunk)

                try:
                    await asyncio.wait_for(message_task, timeout=30.0)
                except asyncio.TimeoutError:
                    pass

                if audio_chunks:
                    import wave
                    full_audio = b''.join(audio_chunks)

                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(output_path), 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(self.output_rate)
                        wf.writeframes(full_audio)

                    return str(output_path)
                else:
                    return ""

            except Exception:
                return ""
            finally:
                self.audio_enabled = original_audio_enabled
                try:
                    await self.close()
                except:
                    pass

        try:
            return asyncio.run(_generate())
        except (KeyboardInterrupt, Exception):
            return ""
