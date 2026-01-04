"""
Doubao (ByteDance) Real-time Translation Client
Implements real-time speech-to-speech and speech-to-text translation
using Doubao's AST (Automatic Simultaneous Translation) API
"""

import os
import sys
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
import io

# Try to import av (PyAV) for Opus decoding
try:
    import av
    AV_AVAILABLE = True
except ImportError:
    AV_AVAILABLE = False
    print("[WARN] PyAV not installed. Doubao audio playback requires PyAV.")
    print("[WARN] Install with: pip install av")

from translation_client_base import BaseTranslationClient
from livetranslate_client import load_glossary

# Add python_protogen to path for protobuf imports
current_dir = os.path.dirname(os.path.abspath(__file__))
protogen_dir = os.path.join(current_dir, "python_protogen")
if protogen_dir not in sys.path:
    sys.path.insert(0, protogen_dir)

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
        self.output_chunk = 1600  # 100ms @ 16kHz (for s2s mode)
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
        """Doubao AST API outputs 16kHz audio (only 16000/48000 supported)"""
        return 16000  # Fixed: Doubao only supports 16000 or 48000, not 24000

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

            # Configure session after connection
            await self.configure_session()

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
            # Use PCM format (as in official demo) - direct playback without decoding
            if self.mode == "s2s":
                request.target_audio.format = "pcm"  # PCM format for direct playback
                request.target_audio.rate = self.output_rate  # 16000Hz (only 16000/48000 supported)
                request.target_audio.bits = 16  # 16-bit PCM
                request.target_audio.channel = 1  # Mono

            # Request parameters
            request.request.mode = self.mode
            request.request.source_language = self.source_language
            request.request.target_language = self.target_language

            # Configure corpus (glossary, hot words, etc.)
            if self.glossary:
                # Set glossary_list (map<string, string>)
                for source_term, target_term in self.glossary.items():
                    request.request.corpus.glossary_list[source_term] = target_term
                print(f"[OK] Loaded {len(self.glossary)} glossary terms into Doubao corpus")

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

    async def send_keepalive(self):
        """发送空包作为keepalive，测试是否能保持session活跃"""
        if not self.is_connected or not self.ws:
            return False

        try:
            print(f"[KEEPALIVE] Sending empty packet as keepalive")
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.TaskRequest
            request.source_audio.binary_data = b""  # 空字节

            await self.ws.send(request.SerializeToString())
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send keepalive: {e}")
            return False

    async def send_audio_chunk(self, audio_data: bytes):
        """Send audio data chunk for translation"""
        if not self.is_connected or not self.ws:
            print("[WARN] Not connected, cannot send audio")
            return

        try:
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.TaskRequest

            # 测试：如果音频数据为空，发送空包作为keepalive
            if len(audio_data) == 0:
                print(f"[TEST] Sending EMPTY audio chunk as keepalive")
                request.source_audio.binary_data = b""  # 空字节
            else:
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

                # Source language recognition (ASR)
                if event_type == self.EVENT_ASR_DELTA:
                    # Source language incremental recognition
                    source_text = response.text
                    if source_text and on_text_received:
                        on_text_received(f"[源] {source_text}")

                # Translation delta (incremental text) - skip displaying
                elif event_type == self.EVENT_TRANSLATE_DELTA:
                    pass  # Don't show incremental updates

                # Translation done (complete sentence)
                elif event_type == self.EVENT_TRANSLATE_DONE:
                    text = response.text
                    if text and on_text_received:
                        on_text_received(f"[译] {text}")

                # Audio delta (incremental audio data)
                elif event_type == self.EVENT_AUDIO_DELTA:
                    pcm_data = response.data
                    if pcm_data and self.audio_enabled:
                        # Direct playback - Doubao returns PCM format
                        self.audio_playback_queue.put(pcm_data)

                # Session finished
                elif event_type == Type.SessionFinished:
                    print("[OK] Doubao session finished")
                    break

                # Session failed/canceled
                elif event_type in [Type.SessionFailed, Type.SessionCanceled]:
                    print(f"[ERROR] Doubao session failed: {response.response_meta.Message}")
                    break

                # Unknown event - still collect audio data (like official SDK)
                elif event_type != self.EVENT_USAGE and response.data:
                    if self.audio_enabled:
                        self.audio_playback_queue.put(response.data)

        except Exception as e:
            print(f"[ERROR] Doubao message handling error: {e}")
        finally:
            self.is_connected = False

    async def close(self):
        """Close connection and cleanup resources"""
        if not self.is_connected:
            return

        self.is_connected = False

        try:
            # Send FinishSession request
            if self.ws and self.session_id:
                request = TranslateRequest()
                request.request_meta.SessionID = self.session_id
                request.event = Type.FinishSession

                await asyncio.wait_for(self.ws.send(request.SerializeToString()), timeout=1.0)
                print("[OK] Doubao FinishSession request sent")

        except asyncio.TimeoutError:
            print("[WARN] FinishSession request timeout")
        except Exception as e:
            print(f"[WARN] Error sending FinishSession: {e}")

        # Close WebSocket with timeout
        if self.ws:
            try:
                # Close with shorter timeout to avoid hanging
                await asyncio.wait_for(self.ws.close(), timeout=1.0)
                await asyncio.sleep(0.1)  # Give time for cleanup
            except asyncio.TimeoutError:
                print("[WARN] WebSocket close timeout")
            except RuntimeError as e:
                # Suppress "no running event loop" errors during shutdown
                if "event loop" not in str(e).lower():
                    print(f"[WARN] Error closing WebSocket: {e}")
            except Exception as e:
                print(f"[WARN] Error closing WebSocket: {e}")
            finally:
                self.ws = None

        # Clear audio queue to prevent buffered audio from playing
        while not self.audio_playback_queue.empty():
            try:
                self.audio_playback_queue.get_nowait()
            except:
                break

        # Stop audio player
        if self.audio_player_thread and self.audio_player_thread.is_alive():
            self.audio_playback_queue.put(None)  # Signal to stop
            self.audio_player_thread.join(timeout=2)

        # Terminate PyAudio
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()

        print("[OK] Doubao connection closed")

    def start_audio_player(self):
        """Start audio playback thread for s2s mode"""
        if not self.audio_enabled or self.audio_player_thread:
            return

        self.audio_player_thread = threading.Thread(
            target=self._audio_player_task,
            daemon=True
        )
        self.audio_player_thread.start()

    def _decode_opus_to_pcm(self, opus_data: bytes) -> bytes:
        """Decode Opus audio data to PCM using PyAV"""
        if not AV_AVAILABLE:
            print("[ERROR] PyAV not available, cannot decode Opus audio")
            return b''

        try:
            # Create a BytesIO object from opus data
            input_stream = io.BytesIO(opus_data)

            # Open container (ogg with opus codec)
            container = av.open(input_stream, format='ogg')

            # Get audio stream
            audio_stream = container.streams.audio[0]

            # Decode frames
            pcm_frames = []
            for frame in container.decode(audio=0):
                # Resample to target rate if needed
                frame = frame.reformat(
                    format='s16',  # 16-bit signed PCM
                    layout='mono',  # Mono
                    rate=self.output_rate  # 24kHz
                )
                # Convert to bytes
                pcm_frames.append(frame.to_ndarray().tobytes())

            container.close()

            # Combine all frames
            pcm_data = b''.join(pcm_frames)
            return pcm_data

        except Exception as e:
            print(f"[ERROR] Opus decode failed: {e}")
            import traceback
            traceback.print_exc()
            return b''  # Return empty data on failure

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

                # Doubao outputs PCM format, write directly
                stream.write(audio_data)

        except Exception as e:
            print(f"[ERROR] Audio playback error: {e}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
