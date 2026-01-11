"""
OpenAI Realtime API Client
Implements real-time audio translation using OpenAI's Realtime API

S2T Mode (audio_enabled=False): Uses streaming transcription API (intent=transcription)
          with gpt-4o-transcribe + separate GPT translation for accurate results
          without conversation interference

S2S Mode (audio_enabled=True): Uses conversation API for audio-to-audio translation
"""

import os
import base64
import asyncio
import json
import audioop
import websockets
from typing import Dict, Optional
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio

# 导入基础类（已包含 OutputMixin）
from translation_client_base import BaseTranslationClient, TranslationProvider
# 导入统一的输出管理器
from output_manager import Out

try:
    from python_socks.async_.asyncio import Proxy
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False

# OpenAI client for GPT translation (separate from WebSocket)
try:
    from openai import OpenAI
    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False


class OpenAIClient(BaseTranslationClient):
    """
    OpenAI Realtime API 客户端

    支持 S2S 和 S2T 两种模式：
    - S2S (audio_enabled=True): 语音输入 → Realtime API → 语音输出
    - S2T (audio_enabled=False): 语音输入 → gpt-4o-transcribe (streaming ASR) → GPT翻译 → 文本输出

    S2T 模式使用两阶段处理：
    1. gpt-4o-transcribe: 流式语音识别（纯ASR，无对话）
    2. GPT-4o-mini: 文本翻译（高质量翻译）

    继承自 BaseTranslationClient，已包含：
    - OutputMixin: 统一的输出接口
    """

    # 类属性，用于识别 provider
    provider = TranslationProvider.OPENAI

    # OpenAI Realtime API 使用 24kHz（输入和输出）
    AUDIO_RATE = 24000

    # 支持的音色列表
    SUPPORTED_VOICES = {
        "alloy": "Alloy (中性)",
        "ash": "Ash (男声)",
        "ballad": "Ballad (男声)",
        "cedar": "Cedar (中性) ⭐ 推荐",
        "coral": "Coral (女声)",
        "echo": "Echo (男声)",
        "marin": "Marin (中性) ⭐ 推荐",
        "sage": "Sage (女声)",
        "shimmer": "Shimmer (女声)",
        "verse": "Verse (男声)"
    }

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = "marin",
        audio_enabled: bool = True,
        model: str = "gpt-4o-mini-realtime-preview",
        transcribe_model: str = "gpt-4o-transcribe",
        translation_model: str = "gpt-4o-mini",
        **kwargs
    ):
        """
        初始化 OpenAI 翻译客户端

        Args:
            api_key: OpenAI API Key
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            voice: 音色选择 (仅 S2S 模式)
            audio_enabled: 是否启用音频输出（True=S2S, False=S2T）
            model: S2S 模式的 Realtime 模型名称
            transcribe_model: S2T 模式的转录模型 (gpt-4o-transcribe / gpt-4o-mini-transcribe)
            translation_model: S2T 模式的翻译模型 (gpt-4o-mini / gpt-4o)
        """
        if not api_key:
            raise ValueError("API key cannot be empty.")

        # OpenAI 特定配置
        self.model = model
        self.transcribe_model = transcribe_model
        self.translation_model = translation_model
        self.ws = None

        # 音频配置（OpenAI 使用 24kHz PCM16）
        self._input_rate = self.AUDIO_RATE
        self._input_chunk = 2400  # 100ms @ 24kHz
        self._input_format = pyaudio.paInt16
        self._input_channels = 1

        # 调用父类 __init__
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            **kwargs
        )

        # S2S 输出门控
        self._s2s_expect_response = False
        self._s2s_has_user_audio = False
        self._s2s_speech_rms_threshold = 500

        # S2T 模式：OpenAI SDK 客户端用于翻译
        self._openai_client = None
        if not audio_enabled and OPENAI_SDK_AVAILABLE:
            self._openai_client = OpenAI(api_key=api_key)

        # S2T: 上下文追踪
        self._previous_transcription = ""
        self._previous_translation = ""

        # S2T: Delta 增量转录追踪（用于渐进式显示）
        self._current_item_id = None
        self._current_delta_transcript = ""

        # 语言名称映射
        self.lang_names = {
            "en": "English",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "fr": "French",
            "de": "German",
            "es": "Spanish"
        }

    @property
    def input_rate(self) -> int:
        """输入采样率（麦克风）"""
        return self._input_rate

    @property
    def output_rate(self) -> int:
        """输出采样率（仅 S2S）"""
        return self.AUDIO_RATE

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """获取支持的音色列表"""
        return cls.SUPPORTED_VOICES.copy()

    def _get_api_url(self) -> str:
        """根据模式返回不同的 API URL"""
        if self.audio_enabled:
            # S2S: 使用会话模式
            return f"wss://api.openai.com/v1/realtime?model={self.model}"
        else:
            # S2T: 使用纯转录模式
            return "wss://api.openai.com/v1/realtime?intent=transcription"

    async def connect(self):
        """建立 WebSocket 连接"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        api_url = self._get_api_url()

        try:
            # 检查代理配置
            proxy_url = (os.getenv("HTTP_PROXY") or
                        os.getenv("http_proxy") or
                        os.getenv("GLOBAL_AGENT_HTTP_PROXY"))

            if PROXY_AVAILABLE and proxy_url:
                self.output_debug(f"使用代理: {proxy_url}")
                try:
                    proxy = Proxy.from_url(proxy_url)
                    sock = await proxy.connect(
                        dest_host="api.openai.com",
                        dest_port=443,
                        timeout=10
                    )
                    self.ws = await websockets.connect(
                        api_url,
                        extra_headers=headers,
                        sock=sock,
                        server_hostname="api.openai.com"
                    )
                except Exception as proxy_error:
                    self.output_warning(f"代理连接失败: {proxy_error}，尝试直连...")
                    self.ws = await websockets.connect(
                        api_url,
                        extra_headers=headers
                    )
            else:
                self.ws = await websockets.connect(
                    api_url,
                    extra_headers=headers
                )

            self.is_connected = True
            mode = "S2S" if self.audio_enabled else "S2T (streaming transcription)"
            self.output_status(f"已连接到 OpenAI Realtime API ({mode})")

            # For S2S, configure immediately; for S2T, wait for transcription_session.created
            if self.audio_enabled:
                await self._configure_s2s_session()
        except Exception as e:
            self.output_error(f"连接失败: {e}", exc_info=True)
            self.is_connected = False
            raise

    async def configure_session(self):
        """配置会话 - S2S立即配置，S2T等待服务器创建会话后配置"""
        # This method is called from connect() for S2S
        # For S2T, it's called when transcription_session.created event is received
        if self.audio_enabled:
            await self._configure_s2s_session()
        else:
            await self._configure_s2t_session()

    async def _configure_s2t_session(self):
        """配置 S2T 会话 - 使用纯转录模式"""
        # Map language codes to what OpenAI expects
        lang = self.source_language
        if lang == "zh":
            lang = "zh"  # Chinese
        elif lang == "en":
            lang = "en"  # English

        # Build transcription prompt with technical context
        # TODO: Move technical terms to external config (e.g., .env or glossary.json)
        #       to avoid hardcoding them in the code
        transcription_config = {
            "model": self.transcribe_model,
            "language": lang,
        }

        # Add prompt for better technical term recognition
        if lang == "en":
            transcription_config["prompt"] = (
                "Technical terms: AI agent, Python, Jupyter notebook, CLI, API, "
                "dev server, VPN, cluster, customer profile, JSON, YAML. "
                "Proper nouns: Marimo, Hatisha."
            )

        # For transcription intent: use transcription_session.update with session wrapper
        config = {
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",
                "input_audio_transcription": transcription_config,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 500,  # Increased to capture more context
                    "silence_duration_ms": 700,  # Increased to avoid cutting off mid-sentence
                },
                "input_audio_noise_reduction": {
                    "type": "near_field"
                }
            }
        }

        self.output_debug(f"Sending S2T config: {json.dumps(config, indent=2)}")
        await self.ws.send(json.dumps(config))
        self.output_status(f"S2T 会话已配置: {self.transcribe_model} + {self.translation_model}")

    async def _configure_s2s_session(self):
        """配置 S2S 会话 - 使用会话模式"""
        instructions = self._build_s2s_instructions()

        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": instructions,
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 300
                },
                "temperature": 0.6,
                "max_response_output_tokens": 4096
            }
        }

        await self.ws.send(json.dumps(config))

    def _build_s2s_instructions(self) -> str:
        """构建 S2S 模式的指令"""
        source = self.lang_names.get(self.source_language, self.source_language)
        target = self.lang_names.get(self.target_language, self.target_language)

        instructions = f"""You are a real-time interpreter. Translate {source} speech to {target}.
Output ONLY the translation. No greetings, no confirmations, no questions.
If silence, output nothing."""

        if self.glossary:
            terms = ", ".join([f"{s}={t}" for s, t in list(self.glossary.items())[:20]])
            instructions += f"\nTerminology: {terms}"

        return instructions

    def _translate_text(self, text: str) -> str:
        """
        使用 GPT 翻译文本（S2T 模式）

        Args:
            text: 源语言文本

        Returns:
            翻译后的文本
        """
        if not self._openai_client:
            self.output_warning("OpenAI SDK 不可用，跳过翻译")
            return ""

        try:
            source_lang = self.lang_names.get(self.source_language, self.source_language)
            target_lang = self.lang_names.get(self.target_language, self.target_language)

            system_content = f"""You are a professional translator. Translate {source_lang} to {target_lang}.

Rules:
- Output ONLY the translation, nothing else
- Preserve technical terms and proper nouns
- Maintain natural, fluent {target_lang}
- Do not add explanations or notes"""

            # 添加上下文以提高连贯性
            if self._previous_transcription:
                system_content += f"""

Previous context:
"{self._previous_transcription}"
Use this for continuity."""

            response = self._openai_client.chat.completions.create(
                model=self.translation_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            result = response.choices[0].message.content
            return result.strip() if result else ""

        except Exception as e:
            self.output_error(f"翻译失败: {e}")
            return ""

    async def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块"""
        if not self.is_connected or not self.ws:
            return

        try:
            if self.audio_enabled:
                try:
                    if audioop.rms(audio_data, 2) > self._s2s_speech_rms_threshold:
                        self._s2s_has_user_audio = True
                except Exception:
                    pass

            event = {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_data).decode()
            }
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.output_error(f"发送音频块失败: {e}")
            self.is_connected = False

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息"""
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    event_type = event.get("type")

                    # Debug: log all event types
                    if not self.audio_enabled:
                        self.output_debug(f"Received event: {event_type}")

                    # ======== 共享事件 ========
                    if event_type == "session.created" or event_type == "session.updated":
                        pass

                    elif event_type == "transcription_session.created":
                        # S2T: 转录会话已创建，现在发送配置
                        self.output_status("Transcription session created, configuring...")
                        await self._configure_s2t_session()

                    elif event_type == "transcription_session.updated":
                        self.output_debug("Transcription session updated")

                    elif event_type == "input_audio_buffer.speech_started":
                        pass

                    elif event_type == "input_audio_buffer.speech_stopped":
                        if self.audio_enabled and self._s2s_has_user_audio:
                            self._s2s_expect_response = True
                        else:
                            self._s2s_expect_response = False
                        self._s2s_has_user_audio = False

                    elif event_type == "input_audio_buffer.committed":
                        # 转录模式：音频块已提交处理
                        pass

                    # ======== S2T 转录模式事件 ========
                    elif event_type == "conversation.item.created":
                        # 新的转录项创建 - 重置 delta 状态
                        item = event.get("item", {})
                        item_id = item.get("id", "")
                        if item_id:
                            self._current_item_id = item_id
                            self._current_delta_transcript = ""

                    elif event_type == "conversation.item.input_audio_transcription.delta":
                        # 增量转录 - 实时显示部分结果
                        item_id = event.get("item_id", "")
                        delta = event.get("delta", "")
                        if item_id == self._current_item_id and delta:
                            self._current_delta_transcript += delta
                            await self._handle_s2t_delta(self._current_delta_transcript)

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # 转录完成 - 这是纯 ASR 结果（完整句子）
                        item_id = event.get("item_id", "")
                        transcript = event.get("transcript", "")
                        if item_id == self._current_item_id and transcript and transcript.strip():
                            # 重置 delta 状态
                            self._current_delta_transcript = ""
                            # 处理完整转录（包括最终翻译）
                            await self._handle_s2t_transcription(transcript)

                    # ======== S2S 会话模式事件 ========
                    elif event_type == "response.audio.delta" and self.audio_enabled:
                        if not self._s2s_expect_response:
                            continue
                        audio_b64 = event.get("delta", "")
                        if audio_b64:
                            audio_data = base64.b64decode(audio_b64)
                            self._queue_audio(audio_data)

                    elif event_type == "response.audio_transcript.done":
                        if not self._s2s_expect_response:
                            continue
                        transcript = event.get("transcript", "")
                        self.output_translation(transcript, extra_metadata={"provider": "openai", "mode": "S2S"})

                    elif event_type == "response.done":
                        self._s2s_expect_response = False

                    # ======== 错误处理 ========
                    elif event_type == "error":
                        error = event.get("error", {})
                        error_code = error.get("code", "Unknown")
                        error_msg = error.get("message", "Unknown error")
                        self.output_error(f"{error_code}: {error_msg}")

                        if "connection" in error_code.lower() or "unauthorized" in error_code.lower():
                            self.is_connected = False
                            break

                except json.JSONDecodeError as e:
                    self.output_warning(f"解析消息失败: {e}")
                    continue
                except Exception as e:
                    self.output_warning(f"处理事件时出错: {e}")
                    continue

        except websockets.exceptions.ConnectionClosed:
            self.output_warning("WebSocket 连接已关闭")
            self.is_connected = False
        except Exception as e:
            self.output_error(f"消息处理错误: {e}", exc_info=True)
            self.is_connected = False

    async def _handle_s2t_delta(self, partial_transcript: str):
        """处理 S2T 模式的增量转录（Delta 事件）

        渐进式显示：立即显示英文并翻译为中文，随着 delta 更新而更新
        """
        if not partial_transcript or not partial_transcript.strip():
            return

        partial_transcript = partial_transcript.strip()

        # 分词检查：确保有足够内容才显示
        if self.source_language == "zh":
            words = list(partial_transcript)
            min_words = 3  # 至少 3 个字
        else:
            words = partial_transcript.split()
            min_words = 2  # 至少 2 个词

        if len(words) < min_words:
            return

        # 避免重复翻译相同内容（检查完整文本而非单词列表）
        if partial_transcript == self._previous_transcription:
            return

        # 1. 先立即显示英文源文本（不等翻译）
        self.output_subtitle(
            target_text=partial_transcript,
            source_text="",
            is_final=False,
            extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Delta-Source"}
        )

        # 2. 立即翻译并显示中文（即使是部分文本）
        partial_translation = self._translate_text(partial_transcript)

        if partial_translation:
            # 显示翻译结果（双语）
            self.output_subtitle(
                target_text=partial_translation,
                source_text=partial_transcript,
                is_final=False,
                extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Delta-Translation"}
            )

            # 更新临时上下文
            self._previous_transcription = partial_transcript
            self._previous_translation = partial_translation

    async def _handle_s2t_transcription(self, transcript: str):
        """处理 S2T 模式的转录结果（完整句子）

        完成时做最终翻译。如果与之前 delta 翻译的文本相同，可能复用翻译；
        否则重新翻译以获得更准确的结果（因为现在有完整上下文）
        """
        # 检查是否需要重新翻译
        # 如果完整转录与最后的 delta 转录相同，可以复用之前的翻译
        if transcript == self._previous_transcription and self._previous_translation:
            translation = self._previous_translation
        else:
            # 完整句子可能与 delta 不同，或首次翻译，重新翻译以获得更好质量
            translation = self._translate_text(transcript)

        if translation:
            # 输出最终翻译结果（标记为 final）
            self.output_subtitle(
                target_text=translation,
                source_text=transcript,
                is_final=True,
                extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Final"}
            )

            # 更新上下文
            self._previous_transcription = transcript
            self._previous_translation = translation

    async def close(self):
        """关闭连接并清理资源"""
        self.output_status("关闭连接...")
        self.is_connected = False

        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=2.0)
                self.output_debug("WebSocket 已关闭")
            except asyncio.TimeoutError:
                self.output_warning("WebSocket 关闭超时")
            except Exception as e:
                self.output_warning(f"关闭 WebSocket 时出错: {e}")

    def generate_voice_sample_file(self, voice: str, text: str = "This is a common phrase used in business meetings."):
        """
        生成音色样本文件（OpenAI 实现）
        """
        from pathlib import Path
        from paths import VOICE_SAMPLES_DIR, ASSETS_DIR

        filename = f"openai_{voice}.wav"
        filepath = VOICE_SAMPLES_DIR / filename

        if filepath.exists():
            return str(filepath)

        standard_audio = ASSETS_DIR / "voice_sample_input_24k.wav"
        if not standard_audio.exists():
            return ""

        async def _generate():
            try:
                original_voice = self.voice
                original_audio_enabled = self.audio_enabled
                self.voice = voice
                self.audio_enabled = True

                await self.connect()

                instructions = self._build_s2s_instructions()
                sample_config = {
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "instructions": instructions,
                        "voice": self.voice,
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 2000
                        },
                        "temperature": 0.8,
                        "max_response_output_tokens": 4096
                    }
                }
                await self.ws.send(json.dumps(sample_config))

                with open(standard_audio, 'rb') as f:
                    f.seek(44)
                    audio_data = f.read()

                audio_chunks = []
                response_complete = False

                async def collect_messages():
                    nonlocal audio_chunks, response_complete
                    try:
                        async for message in self.ws:
                            try:
                                event = json.loads(message)
                                event_type = event.get("type", "")

                                if event_type == "response.audio.delta" and self.audio_enabled:
                                    audio_b64 = event.get("delta", "")
                                    if audio_b64:
                                        chunk_data = base64.b64decode(audio_b64)
                                        audio_chunks.append(chunk_data)

                                elif event_type == "response.done":
                                    response_complete = True
                                    break

                                elif event_type == "error":
                                    break

                            except json.JSONDecodeError:
                                continue
                            except Exception:
                                continue

                            if response_complete:
                                break

                    except Exception:
                        pass

                message_task = asyncio.create_task(collect_messages())
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

                silence_chunk_size = 100 * 1024
                for i in range(0, len(silence_data), silence_chunk_size):
                    chunk = silence_data[i:i + silence_chunk_size]
                    await self.send_audio_chunk(chunk)

                try:
                    await asyncio.wait_for(message_task, timeout=30.0)
                except asyncio.TimeoutError:
                    pass

                if audio_chunks:
                    full_audio = b''.join(audio_chunks)

                    import wave
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(filepath), 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(self.output_rate)
                        wf.writeframes(full_audio)

                    return str(filepath)
                else:
                    return ""

            except Exception:
                return ""
            finally:
                self.voice = original_voice
                self.audio_enabled = original_audio_enabled
                try:
                    await self.close()
                except:
                    pass

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _generate())
                return future.result(timeout=40)
        except Exception:
            return ""
