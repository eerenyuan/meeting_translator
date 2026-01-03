"""
Doubao (ByteDance) Real-time Translation Client
Implements real-time speech-to-speech and speech-to-text translation
using Doubao's AST (Automatic Simultaneous Translation) API
"""

import os
import uuid
import asyncio
import websockets
from websockets import Headers
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio
import queue
import threading
from typing import Callable, Optional, Dict

from translation_client_base import BaseTranslationClient
from livetranslate_client import load_glossary
from python_protogen.products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from python_protogen.common.events_pb2 import Type


class DoubaoClient(BaseTranslationClient):
    """Doubao (ByteDance) AST translation client"""

    # Doubao AST API uses 16kHz for input
    AUDIO_RATE = 16000

    # Event type constants
    EVENT_ASR_START = 650          # 识别开始
    EVENT_ASR_DELTA = 651          # 识别增量（源语言）
    EVENT_ASR_DONE = 652           # 识别完成（源语言）
    EVENT_TRANSLATE_START = 653    # 翻译开始
    EVENT_TRANSLATE_DELTA = 654    # 翻译增量（目标语言）
    EVENT_TRANSLATE_DONE = 655     # 翻译完成（目标语言）
    EVENT_AUDIO_START = 350        # 音频合成开始
    EVENT_AUDIO_DELTA = 352        # 音频增量
    EVENT_AUDIO_DONE = 351         # 音频完成
    EVENT_USAGE = 154              # 计费信息

    def __init__(
        self,
        api_key: str,  # 对应 doubao_app_id
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = None,
        audio_enabled: bool = True,
        glossary_file: Optional[str] = None,
        access_token: Optional[str] = None,  # doubao_access_token
        **kwargs
    ):
        super().__init__(api_key, source_language, target_language, voice, audio_enabled, glossary_file)

        # Doubao specific configuration
        self.app_key = api_key  # doubao_app_id
        self.access_key = access_token  # doubao_access_token
        self.ws_url = "wss://openspeech.bytedance.com/api/v4/ast/v2/translate"
        self.resource_id = "volc.service_type.10053"

        # Mode: s2s (speech-to-speech) or s2t (speech-to-text)
        # Use s2t when audio_enabled=False to save costs
        self.mode = "s2s" if audio_enabled else "s2t"

        self.ws = None
        self.session_id = None

        # Load glossary
        self.glossary = load_glossary(glossary_file)
        if self.glossary:
            print(f"[OK] Loaded glossary with {len(self.glossary)} terms")

        # Audio configuration
        self.input_chunk = 1600  # 100ms @ 16kHz
        self.output_chunk = 2400  # 100ms @ 24kHz (for s2s mode)
        self.input_format = pyaudio.paInt16
        self.output_format = pyaudio.paInt16
        self.channels = 1

        # Audio playback (for s2s mode)
        self.audio_playback_queue = queue.Queue()
        self.audio_player_thread = None
        self.pyaudio_instance = None
        if audio_enabled:
            self.pyaudio_instance = pyaudio.PyAudio()

    @property
    def input_rate(self) -> int:
        """Doubao AST API requires 16kHz input"""
        return self.AUDIO_RATE

    @property
    def output_rate(self) -> int:
        """Doubao AST API outputs 24kHz audio"""
        return 24000

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        Doubao AST does not support voice selection
        The voice is determined by the service backend
        """
        return {
            "default": "Default (Auto)"
        }

    async def connect(self):
        """Establish WebSocket connection to Doubao AST API"""
        if self.is_connected:
            print("[WARN] Already connected to Doubao API")
            return

        try:
            # Generate connection ID
            conn_id = str(uuid.uuid4())

            # Build request headers
            headers = Headers({
                "X-Api-App-Key": self.app_key,
                "X-Api-Access-Key": self.access_key,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Connect-Id": conn_id
            })

            # Establish WebSocket connection
            self.ws = await websockets.connect(
                self.ws_url,
                extra_headers=headers,
                max_size=1000000000,
                ping_interval=None
            )

            log_id = self.ws.response_headers.get('X-Tt-Logid', 'N/A')
            print(f"[OK] Connected to Doubao API (log_id={log_id})")

            self.is_connected = True

        except Exception as e:
            print(f"[ERROR] Doubao connection failed: {e}")
            raise

    async def configure_session(self):
        """Configure Doubao translation session"""
        if not self.is_connected:
            raise Exception("Must connect before configuring session")

        try:
            # Generate session ID
            self.session_id = str(uuid.uuid4())

            # Send StartSession request
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.StartSession
            request.user.uid = "meeting_translator"
            request.user.did = "meeting_translator"

            # Source audio configuration
            request.source_audio.format = "wav"
            request.source_audio.rate = self.input_rate
            request.source_audio.bits = 16
            request.source_audio.channel = 1

            # Target audio configuration (only for s2s mode)
            if self.mode == "s2s":
                request.target_audio.format = "ogg_opus"
                request.target_audio.rate = self.output_rate

            # Request parameters
            request.request.mode = self.mode
            request.request.source_language = self.source_language
            request.request.target_language = self.target_language

            await self.ws.send(request.SerializeToString())

            # Wait for SessionStarted response
            message = await self.ws.recv()
            response = TranslateResponse()
            response.ParseFromString(message)

            if response.event != Type.SessionStarted:
                raise Exception(
                    f"Session start failed: event={response.event}, "
                    f"message={response.response_meta.Message}"
                )

            print(f"[OK] Doubao session configured (ID={self.session_id}, mode={self.mode})")

        except Exception as e:
            print(f"[ERROR] Doubao session configuration failed: {e}")
            raise

    async def send_audio_chunk(self, audio_data: bytes):
        """Send audio data chunk for translation"""
        if not self.is_connected or not self.ws:
            print("[WARN] Not connected, cannot send audio")
            return

        try:
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.TaskRequest
            request.source_audio.binary_data = audio_data

            await self.ws.send(request.SerializeToString())

        except Exception as e:
            print(f"[ERROR] Failed to send audio chunk: {e}")
            self.is_connected = False

    async def handle_server_messages(self, on_text_received: Optional[Callable] = None):
        """Handle incoming messages from Doubao server"""
        try:
            while self.is_connected:
                message = await self.ws.recv()
                response = TranslateResponse()
                response.ParseFromString(message)
                event_type = response.event

                # Ignore source language recognition events (included in input cost, not needed)
                if event_type in [self.EVENT_ASR_START, self.EVENT_ASR_DELTA, self.EVENT_ASR_DONE]:
                    continue

                # Translation start
                elif event_type == self.EVENT_TRANSLATE_START:
                    pass  # Can trigger callback here

                # Translation delta (incremental text)
                elif event_type == self.EVENT_TRANSLATE_DELTA:
                    delta = response.text
                    if delta and on_text_received:
                        on_text_received(f"{delta}")

                # Translation done (complete sentence)
                elif event_type == self.EVENT_TRANSLATE_DONE:
                    text = response.text
                    if text and on_text_received:
                        on_text_received(f" ")  # Add space between sentences

                # Audio synthesis start
                elif event_type == self.EVENT_AUDIO_START:
                    pass  # Can trigger callback here

                # Audio delta (incremental audio data)
                elif event_type == self.EVENT_AUDIO_DELTA:
                    audio_data = response.data
                    if audio_data and self.audio_enabled:
                        self.audio_playback_queue.put(audio_data)

                # Audio done
                elif event_type == self.EVENT_AUDIO_DONE:
                    pass  # Can trigger callback here

                # Usage/billing info
                elif event_type == self.EVENT_USAGE:
                    pass  # Can parse and log billing info

                # Session finished
                elif event_type == Type.SessionFinished:
                    print("[OK] Doubao session finished")
                    break

                # Session failed/canceled
                elif event_type in [Type.SessionFailed, Type.SessionCanceled]:
                    print(f"[ERROR] Doubao session failed: {response.response_meta.Message}")
                    break

        except Exception as e:
            print(f"[ERROR] Doubao message handling error: {e}")
        finally:
            self.is_connected = False

    async def close(self):
        """Close connection and cleanup resources"""
        if not self.is_connected:
            return

        try:
            # Send FinishSession request
            if self.ws and self.session_id:
                request = TranslateRequest()
                request.request_meta.SessionID = self.session_id
                request.event = Type.FinishSession

                await self.ws.send(request.SerializeToString())
                print("[OK] Doubao FinishSession request sent")

        except Exception as e:
            print(f"[WARN] Error sending FinishSession: {e}")

        # Close WebSocket
        if self.ws:
            await self.ws.close()
            self.is_connected = False
            print("[OK] Doubao connection closed")

        # Stop audio player
        if self.audio_player_thread and self.audio_player_thread.is_alive():
            self.audio_playback_queue.put(None)  # Signal to stop
            self.audio_player_thread.join(timeout=2)

        # Terminate PyAudio
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
            print("[OK] PyAudio terminated")

    def start_audio_player(self):
        """Start audio playback thread for s2s mode"""
        if not self.audio_enabled or self.audio_player_thread:
            return

        self.audio_player_thread = threading.Thread(
            target=self._audio_player_task,
            daemon=True
        )
        self.audio_player_thread.start()
        print("[OK] Doubao audio player started")

    def _audio_player_task(self):
        """Audio playback thread"""
        stream = None
        try:
            stream = self.pyaudio_instance.open(
                format=self.output_format,
                channels=self.channels,
                rate=self.output_rate,
                output=True,
                frames_per_buffer=self.output_chunk
            )

            while True:
                audio_data = self.audio_playback_queue.get()
                if audio_data is None:  # Stop signal
                    break

                # Doubao outputs Opus format, decode if needed
                # For now, play directly (PyAudio may need opus decoder)
                stream.write(audio_data)

        except Exception as e:
            print(f"[ERROR] Audio playback error: {e}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            print("[OK] Doubao audio player stopped")
