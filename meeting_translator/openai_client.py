"""
OpenAI Realtime API Client
Implements real-time audio translation using OpenAI's Realtime API

S2T Mode (audio_enabled=False): Uses streaming transcription API (intent=transcription)
          with gpt-4o-transcribe + separate GPT translation for accurate results
          without conversation interference

S2S Mode (audio_enabled=True): Uses conversation API for audio-to-audio translation
"""

import os
import re
import base64
import asyncio
import json
import audioop
import websockets
import time
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
    - S2T (audio_enabled=False): 语音输入 → gpt-4o-mini-transcribe-2025-12-15 (streaming ASR) → GPT翻译 → 文本输出

    S2T 模式使用两阶段处理：
    1. gpt-4o-mini-transcribe-2025-12-15: 流式语音识别（纯ASR，无对话）
       - 90% fewer hallucinations vs Whisper v2
       - 70% fewer hallucinations vs previous gpt-4o-transcribe
       - Optimized for real-world conversational settings
    2. GPT-4o-mini: 文本翻译（高质量翻译）
       - 默认 gpt-4o-mini ($0.15/$0.60 per 1M tokens) 提供最佳速度和质量平衡
       - 可选 gpt-5-nano ($0.05/$0.40 per 1M tokens) 以降低成本（但响应较慢）

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
        transcribe_model: str = "gpt-4o-mini-transcribe-2025-12-15",
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
            transcribe_model: S2T 模式的转录模型 (gpt-4o-mini-transcribe-2025-12-15 / gpt-4o-transcribe / gpt-4o-mini-transcribe)
            translation_model: S2T 模式的翻译模型 (gpt-4o-mini / gpt-5-nano / gpt-5-mini / gpt-4o)
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

        # S2T: 语音活动状态追踪
        self._speech_active = False  # 是否正在说话（speech_started到speech_stopped之间）
        self._last_output_time = 0.0  # 上次输出时间（用于显示Listening提示）
        self._listening_indicator_task = None  # 延迟显示Listening的任务

        # S2T: Delta 增量转录追踪（用于渐进式显示）
        self._current_item_id = None
        self._current_delta_transcript = ""
        self._translated_sentences = []  # 已翻译的句子列表 [(en, zh), ...]
        self._last_sentence_count = 0  # 上次处理的句子数量
        # 显示节流（每50ms或2个新词更新显示）
        self._last_display_time = 0.0
        self._last_display_word_count = 0
        self._display_throttle_ms = 50  # 50ms - 20 updates/sec max
        self._display_word_delta = 2  # 每2个新词更新一次显示
        # 未完成句子的翻译节流（每1秒或4个新词）
        self._last_translation_time = 0.0
        self._last_translation_word_count = 0
        self._translation_throttle_ms = 1000  # 1秒
        self._translation_word_delta = 4  # 每4个新词翻译一次
        self._translation_task = None  # 后台翻译任务
        self._pending_sentence = ""  # 未完成的句子（不以.!?结尾）
        self._pending_translation = ""  # 未完成句子的翻译
        self._last_output_text = ""  # 上次输出的英文文本（用于去重）

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

            # GPT-5/reasoning models use max_completion_tokens, older models use max_tokens
            completion_params = {
                "model": self.translation_model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ],
            }

            # GPT-5 family (gpt-5*) and reasoning models (o1, o3, o4) use max_completion_tokens
            # and don't support temperature parameter (only default temperature=1)
            if self.translation_model.startswith(("gpt-5", "o1", "o3", "o4")):
                completion_params["max_completion_tokens"] = 1000
            else:
                completion_params["max_tokens"] = 1000
                completion_params["temperature"] = 0.3

            response = self._openai_client.chat.completions.create(**completion_params)

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

                    # ======== 共享事件 ========
                    if event_type == "session.created" or event_type == "session.updated":
                        pass

                    elif event_type == "transcription_session.created":
                        # S2T: 转录会话已创建，现在发送配置
                        self.output_status("Transcription session created, configuring...")
                        await self._configure_s2t_session()

                    elif event_type == "transcription_session.updated":
                        pass

                    elif event_type == "input_audio_buffer.speech_started":
                        self._speech_active = True
                        # Start delayed task to show "Listening..." if no output after 3s
                        self._cancel_listening_indicator()
                        self._listening_indicator_task = asyncio.create_task(
                            self._show_listening_indicator_after_delay(3.0)
                        )

                    elif event_type == "input_audio_buffer.speech_stopped":
                        self._speech_active = False
                        self._cancel_listening_indicator()
                        self._s2s_expect_response = self.audio_enabled and self._s2s_has_user_audio
                        self._s2s_has_user_audio = False

                    elif event_type == "input_audio_buffer.committed":
                        pass

                    # ======== S2T Transcription Events ========
                    elif event_type == "conversation.item.created":
                        item_id = event.get("item", {}).get("id", "")
                        if item_id:
                            self._reset_transcription_state(item_id)

                    elif event_type == "conversation.item.input_audio_transcription.delta":
                        item_id = event.get("item_id", "")
                        delta = event.get("delta", "")
                        if item_id == self._current_item_id and delta:
                            self._current_delta_transcript += delta
                            await self._handle_s2t_delta(self._current_delta_transcript)

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        item_id = event.get("item_id", "")
                        transcript = event.get("transcript", "").strip()
                        if item_id == self._current_item_id and transcript:
                            self._cancel_pending_translation()
                            self._current_delta_transcript = ""
                            await self._handle_s2t_transcription(transcript)

                    # ======== S2S Conversation Events ========
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

    async def _show_listening_indicator_after_delay(self, delay_seconds: float):
        """Show 'Listening...' indicator if no output after delay while speech is active."""
        try:
            await asyncio.sleep(delay_seconds)
            time_since_output_ms = time.time() * 1000 - self._last_output_time
            if self._speech_active and time_since_output_ms >= 3000:
                self.output_subtitle(
                    target_text="...",
                    source_text="🎤 Listening...",
                    is_final=False,
                    extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Listening"}
                )
        except asyncio.CancelledError:
            pass

    async def _handle_s2t_delta(self, partial_transcript: str):
        """Process incremental S2T transcription (delta events).

        Splits text into sentences at punctuation marks (.!?,。！？，).
        Complete sentences are translated immediately.
        Incomplete sentences are shown in source language until complete.
        """
        if not partial_transcript or not partial_transcript.strip():
            return

        text = partial_transcript.strip()

        # Split into sentences at punctuation boundaries
        sentence_pattern = r'([.!?,。！？，]+)'
        parts = re.split(sentence_pattern, text)

        # Reassemble: pair each text segment with its trailing punctuation
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            segment = parts[i].strip()
            if segment:
                punctuation = parts[i + 1] if i + 1 < len(parts) else ""
                sentences.append(segment + punctuation)

        # Text after the last punctuation is the incomplete "pending" portion
        pending = parts[-1].strip() if len(parts) % 2 == 1 else ""

        # Translate any new complete sentences (sequentially for proper timestamps)
        if len(sentences) > self._last_sentence_count:
            # Cancel any pending translation task to avoid duplicate output
            if self._translation_task and not self._translation_task.done():
                self._translation_task.cancel()
                self._translation_task = None

            for sentence in sentences[self._last_sentence_count:]:
                await self._translate_and_output_sentence(sentence, is_final=True)
            self._last_sentence_count = len(sentences)
            self._pending_sentence = ""
            self._pending_translation = ""

        # Handle incomplete sentence at the end
        if pending and pending != self._pending_sentence:
            self._pending_sentence = pending
            word_count = len(pending.split())
            time_since_last_translation = time.time() * 1000 - self._last_translation_time

            # Translate if long enough (4+ words) and throttle time passed (800ms)
            if word_count >= 4 and time_since_last_translation >= 800:
                self._last_translation_time = time.time() * 1000
                # Store task reference so it can be cancelled if complete sentence arrives
                self._translation_task = asyncio.create_task(
                    self._translate_and_output_sentence(pending, is_final=False)
                )
            else:
                # Show source text without translation
                self.output_subtitle(
                    target_text="",
                    source_text=pending,
                    is_final=False,
                    extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Pending"}
                )

    async def _translate_and_output_sentence(self, sentence: str, is_final: bool = True):
        """Translate a sentence and output it.

        Args:
            sentence: The sentence to translate
            is_final: If True, adds to history. If False, shows as temporary preview.
        """
        try:
            normalized = self._normalize_text(sentence)
            last_normalized = self._normalize_text(self._last_output_text)

            # Skip non-final outputs if:
            # 1. Same text already output, OR
            # 2. This is a prefix of what was already output (longer version shown)
            if not is_final and normalized and last_normalized:
                if normalized == last_normalized or last_normalized.startswith(normalized):
                    return

            loop = asyncio.get_event_loop()
            translation = await loop.run_in_executor(None, self._translate_text, sentence)

            if translation:
                self.output_subtitle(
                    target_text=translation,
                    source_text=sentence,
                    is_final=is_final,
                    extra_metadata={"provider": "openai", "mode": "S2T", "stage": "Sentence"}
                )

                self._last_output_time = time.time() * 1000
                self._cancel_listening_indicator()

                self._last_output_text = sentence
                self._previous_transcription = sentence
                self._previous_translation = translation

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.output_debug(f"Sentence translation failed: {e}")

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Remove punctuation and whitespace for text comparison."""
        return re.sub(r'[.!?,。！？，\s]+', '', text.lower())

    def _cancel_listening_indicator(self):
        """Cancel any pending listening indicator task."""
        if self._listening_indicator_task:
            self._listening_indicator_task.cancel()
            self._listening_indicator_task = None

    def _cancel_pending_translation(self):
        """Cancel any pending background translation task."""
        if self._translation_task and not self._translation_task.done():
            self._translation_task.cancel()

    def _reset_transcription_state(self, item_id: str):
        """Reset transcription state for a new conversation item."""
        self._current_item_id = item_id
        self._current_delta_transcript = ""
        self._translated_sentences = []
        self._last_sentence_count = 0
        self._pending_sentence = ""
        self._pending_translation = ""
        self._last_display_time = 0.0
        self._last_display_word_count = 0
        self._last_translation_time = 0.0
        self._last_translation_word_count = 0
        self._last_output_text = ""

    async def _handle_s2t_transcription(self, transcript: str):
        """Handle completed S2T transcription (triggered by VAD silence detection).

        Flushes any remaining pending content that wasn't processed by delta handler.
        """
        # Flush pending content (text without punctuation at the end)
        if self._pending_sentence and len(self._pending_sentence.strip()) >= 2:
            await self._translate_and_output_sentence(self._pending_sentence, is_final=True)
            self._pending_sentence = ""
            self._pending_translation = ""

        self._previous_transcription = transcript

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
