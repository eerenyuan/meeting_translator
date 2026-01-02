"""
OpenAI Realtime API Client
Implements real-time audio translation using OpenAI's Realtime API
"""

import os
import time
import base64
import asyncio
import json
import websockets
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio
import queue
import threading
import traceback
from typing import Callable, Optional, Dict

from translation_client_base import BaseTranslationClient
from livetranslate_client import load_glossary

try:
    from python_socks.async_.asyncio import Proxy
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False


class OpenAIRealtimeClient(BaseTranslationClient):
    """OpenAI Realtime API translation client"""

    # OpenAI Realtime API uses 24kHz for both input and output
    AUDIO_RATE = 24000

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = "alloy",
        audio_enabled: bool = True,
        glossary_file: Optional[str] = None,
        model: str = "gpt-realtime-2025-08-28",
        **kwargs
    ):
        super().__init__(api_key, source_language, target_language, voice, audio_enabled, glossary_file)

        self.model = model
        self.ws = None
        self.api_url = f"wss://api.openai.com/v1/realtime?model={model}"

        # Load glossary
        self.glossary = load_glossary(glossary_file)
        if self.glossary:
            print(f"[OK] Loaded glossary with {len(self.glossary)} terms")

        # Audio configuration (OpenAI uses 24kHz PCM16)
        self.input_chunk = 2400  # 100ms @ 24kHz
        self.output_chunk = 2400
        self.input_format = pyaudio.paInt16
        self.output_format = pyaudio.paInt16
        self.channels = 1

        # Audio playback
        self.audio_playback_queue = queue.Queue()
        self.audio_player_thread = None
        self.pyaudio_instance = pyaudio.PyAudio()

    @property
    def input_rate(self) -> int:
        return self.AUDIO_RATE

    @property
    def output_rate(self) -> int:
        return self.AUDIO_RATE

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """OpenAI Realtime API voices"""
        return {
            "alloy": "Alloy (Neutral)",
            "echo": "Echo (Male)",
            "shimmer": "Shimmer (Female)",
            "ash": "Ash (Male)",
            "ballad": "Ballad (Male)",
            "coral": "Coral (Female)",
            "sage": "Sage (Female)",
            "verse": "Verse (Male)"
        }

    async def connect(self):
        """Establish WebSocket connection to OpenAI Realtime API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        try:
            # Check for proxy configuration
            proxy_url = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or "http://127.0.0.1:7890"

            if PROXY_AVAILABLE and proxy_url:
                print(f"[INFO] Using proxy: {proxy_url}")
                try:
                    proxy = Proxy.from_url(proxy_url)
                    sock = await proxy.connect(dest_host="api.openai.com", dest_port=443, timeout=10)
                    self.ws = await websockets.connect(
                        self.api_url,
                        extra_headers=headers,
                        sock=sock,
                        server_hostname="api.openai.com"
                    )
                except Exception as proxy_error:
                    print(f"[WARN] Proxy connection failed: {proxy_error}, trying direct connection...")
                    self.ws = await websockets.connect(
                        self.api_url,
                        extra_headers=headers
                    )
            else:
                self.ws = await websockets.connect(
                    self.api_url,
                    extra_headers=headers
                )

            self.is_connected = True
            print(f"[OK] Connected to: {self.api_url}")
            await self.configure_session()
        except Exception as e:
            print(f"[ERROR] Connection failed: {e}")
            self.is_connected = False
            raise

    async def configure_session(self):
        """Configure OpenAI Realtime session"""

        # Build translation instructions using glossary
        instructions = self._build_translation_instructions()

        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"] if self.audio_enabled else ["text"],
                "instructions": instructions,
                "voice": self.voice or "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800
                },
                "temperature": 0.8,
                "max_response_output_tokens": 4096
            }
        }

        print(f"[OK] Session configured: {self.source_language} → {self.target_language}, voice={self.voice}")
        await self.ws.send(json.dumps(config))

    def _build_translation_instructions(self) -> str:
        """Build system instructions for translation"""

        # Map language codes
        lang_map = {
            "zh": "Chinese",
            "en": "English",
            "ja": "Japanese",
            "ko": "Korean",
            "fr": "French",
            "de": "German",
            "es": "Spanish"
        }

        source = lang_map.get(self.source_language, self.source_language)
        target = lang_map.get(self.target_language, self.target_language)

        instructions = f"""You are a real-time interpreter. Your task is to:
1. Listen to {source} speech
2. Translate it into {target} in real-time
3. Speak the translation naturally and fluently
4. Maintain the original meaning and tone
5. Respond ONLY with the translation, no explanations or comments

"""

        # Add glossary if available
        if self.glossary:
            terms = ", ".join([f"{src}={tgt}" for src, tgt in list(self.glossary.items())[:20]])
            instructions += f"\nImportant terminology mappings: {terms}\n"
            instructions += "Use these exact translations for the specified terms.\n"

        return instructions

    async def send_audio_chunk(self, audio_data: bytes):
        """Send audio data to OpenAI Realtime API"""
        if not self.is_connected or not self.ws:
            return

        try:
            # Debug: 统计发送的音频块
            if not hasattr(self, '_audio_chunk_count'):
                self._audio_chunk_count = 0
            self._audio_chunk_count += 1

            if self._audio_chunk_count <= 5 or self._audio_chunk_count % 100 == 0:
                print(f"[DEBUG] Sending audio chunk #{self._audio_chunk_count}, size: {len(audio_data)} bytes")

            event = {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_data).decode()
            }
            await self.ws.send(json.dumps(event))
        except Exception as e:
            print(f"[ERROR] Failed to send audio chunk: {e}")
            self.is_connected = False

    def _audio_player_task(self):
        """Audio playback thread"""
        stream = None
        try:
            stream = self.pyaudio_instance.open(
                format=self.output_format,
                channels=self.channels,
                rate=self.AUDIO_RATE,
                output=True,
                frames_per_buffer=self.output_chunk,
            )
            print(f"[OK] Audio player started ({self.AUDIO_RATE}Hz, mono)")

            while self.is_connected or not self.audio_playback_queue.empty():
                try:
                    audio_chunk = self.audio_playback_queue.get(timeout=0.1)
                    if audio_chunk is None:
                        break
                    stream.write(audio_chunk)
                    self.audio_playback_queue.task_done()
                except queue.Empty:
                    continue
        except Exception as e:
            print(f"[ERROR] Audio player error: {e}")
            traceback.print_exc()
        finally:
            # Drain remaining queue
            try:
                while not self.audio_playback_queue.empty():
                    leftover = self.audio_playback_queue.get_nowait()
                    if leftover is not None and stream:
                        stream.write(leftover)
                    self.audio_playback_queue.task_done()
            except queue.Empty:
                pass

            time.sleep(0.1)
            if stream:
                stream.stop_stream()
                stream.close()
            print("[OK] Audio player stopped")

    def start_audio_player(self):
        """Start audio playback thread"""
        if not self.audio_enabled:
            return

        if self.audio_player_thread is None or not self.audio_player_thread.is_alive():
            self.audio_player_thread = threading.Thread(
                target=self._audio_player_task,
                daemon=True
            )
            self.audio_player_thread.start()

    async def handle_server_messages(self, on_text_received: Optional[Callable] = None):
        """Handle messages from OpenAI Realtime API"""
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    event_type = event.get("type")

                    # Debug: 打印所有收到的事件类型
                    if event_type not in ["session.created", "session.updated"]:
                        print(f"[DEBUG] Event received: {event_type}")

                    if event_type == "session.created":
                        print("[OK] Session created")

                    elif event_type == "session.updated":
                        print("[OK] Session updated")

                    elif event_type == "response.audio.delta" and self.audio_enabled:
                        # Audio output chunk
                        audio_b64 = event.get("delta", "")
                        if audio_b64:
                            audio_data = base64.b64decode(audio_b64)
                            self.audio_playback_queue.put(audio_data)

                    elif event_type == "response.text.delta":
                        # Translation text (incremental) - for text-only mode
                        delta = event.get("delta", "")
                        print(f"[DEBUG] text.delta: delta='{delta}', full_event_keys={list(event.keys())}")
                        if delta and on_text_received:
                            on_text_received(f"[译增量] {delta}")

                    elif event_type == "response.text.done":
                        # Translation complete - for text-only mode
                        text = event.get("text", "")
                        print(f"[DEBUG] text.done: text='{text}', full_event_keys={list(event.keys())}")
                        if text and on_text_received:
                            on_text_received(f"[译] {text}")

                    elif event_type == "response.audio_transcript.delta":
                        # Translation text (incremental) - for audio mode
                        delta = event.get("delta", "")
                        if delta and on_text_received:
                            on_text_received(f"[译增量] {delta}")

                    elif event_type == "response.audio_transcript.done":
                        # Translation complete - for audio mode
                        transcript = event.get("transcript", "")
                        if transcript and on_text_received:
                            on_text_received(f"[译] {transcript}")

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # Source language transcription
                        # 数据在 event.transcript 字段中
                        transcript = event.get("transcript", "")
                        if not transcript:
                            # 有时也可能在 item.content[0].transcript 中
                            item = event.get("item", {})
                            content = item.get("content", [])
                            if content and len(content) > 0:
                                transcript = content[0].get("transcript", "")

                        print(f"[DEBUG] input_audio_transcription.completed: transcript='{transcript}', full_event_keys={list(event.keys())}")
                        if transcript and on_text_received:
                            on_text_received(f"[源] {transcript}")

                    elif event_type == "response.done":
                        response = event.get("response", {})
                        status = response.get("status", "")
                        if status == "completed":
                            print("\n[OK] Response complete")
                        usage = response.get("usage", {})
                        if usage:
                            total_tokens = usage.get("total_tokens", 0)
                            if total_tokens > 0:
                                print(f"[INFO] Tokens: {total_tokens}")

                    elif event_type == "input_audio_buffer.speech_started":
                        print("\n[🎤] Speech detected")

                    elif event_type == "input_audio_buffer.speech_stopped":
                        print("[🎤] Speech ended")

                    elif event_type == "error":
                        error = event.get("error", {})
                        error_code = error.get("code", "Unknown")
                        error_msg = error.get("message", "Unknown error")
                        print(f"\n[ERROR] {error_code}: {error_msg}")

                        if "connection" in error_code.lower() or "unauthorized" in error_code.lower():
                            self.is_connected = False
                            break

                except json.JSONDecodeError as e:
                    print(f"[WARN] Failed to parse message: {e}")
                    continue
                except Exception as e:
                    print(f"[WARN] Error processing event: {e}")
                    continue

        except websockets.exceptions.ConnectionClosed as e:
            print(f"\n[WARN] Connection closed: {e}")
            self.is_connected = False
        except Exception as e:
            print(f"\n[ERROR] Message handling error: {e}")
            traceback.print_exc()
            self.is_connected = False

    async def close(self):
        """Close connection and cleanup"""
        print("[INFO] Closing OpenAI Realtime connection...")
        self.is_connected = False

        # Close WebSocket
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=2.0)
                print("[OK] WebSocket closed")
            except asyncio.TimeoutError:
                print("[WARN] WebSocket close timeout")
            except Exception as e:
                print(f"[WARN] Error closing WebSocket: {e}")

        # Stop audio player
        if self.audio_player_thread and self.audio_player_thread.is_alive():
            self.audio_playback_queue.put(None)
            self.audio_player_thread.join(timeout=2.0)
            if self.audio_player_thread.is_alive():
                print("[WARN] Audio player thread did not terminate")

        # Terminate PyAudio
        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
                print("[OK] PyAudio terminated")
            except Exception as e:
                print(f"[WARN] Error terminating PyAudio: {e}")
