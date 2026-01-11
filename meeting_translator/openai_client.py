"""
OpenAI Realtime API Client
Implements real-time audio translation using OpenAI's Realtime API
"""

import os
import time
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

import queue
import threading

# 导入基础类（已包含 OutputMixin）
from translation_client_base import BaseTranslationClient, TranslationProvider
# 导入统一的输出管理器
from output_manager import Out

try:
    from python_socks.async_.asyncio import Proxy
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False


class OpenAIClient(BaseTranslationClient):
    """
    OpenAI Realtime API 客户端

    支持 S2S 和 S2T 两种模式：
    - S2S (audio_enabled=True): 语音输入 → 翻译 → 语音输出
    - S2T (audio_enabled=False): 语音输入 → 翻译 → 文本输出

    继承自 BaseTranslationClient，已包含：
    - OutputMixin: 统一的输出接口
    """

    # 类属性，用于识别 provider
    provider = TranslationProvider.OPENAI

    # OpenAI Realtime API 使用 24kHz（输入和输出）
    AUDIO_RATE = 24000

    # 支持的音色列表
    # 来源：https://platform.openai.com/docs/guides/realtime-conversations#voice-options
    # 推荐：marin 和 cedar (最佳质量)
    # 参考：https://openai.com/index/introducing-gpt-realtime/
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
        voice: Optional[str] = "marin",  # 推荐：marin 或 cedar（最佳质量）
        audio_enabled: bool = True,
        model: str = "gpt-realtime-2025-08-28",
        **kwargs  # audio_queue, glossary 等通过 kwargs 传递给父类
    ):
        """
        初始化 OpenAI 翻译客户端

        Args:
            api_key: OpenAI API Key
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            voice: 音色选择
                  推荐：marin 或 cedar (最佳质量)
                  可选：alloy/ash/ballad/coral/echo/sage/shimmer/verse
            audio_enabled: 是否启用音频输出（True=S2S, False=S2T）
            model: OpenAI Realtime 模型名称
            **kwargs: 其他参数（audio_queue, glossary 等传递给父类）

        Note:
            音色选项参考：
            - https://platform.openai.com/docs/guides/realtime-conversations#voice-options
            - https://openai.com/index/introducing-gpt-realtime/ (Marin & Cedar 介绍)
        """
        if not api_key:
            raise ValueError("API key cannot be empty.")

        # OpenAI 特定配置
        self.model = model
        self.ws = None
        self.api_url = f"wss://api.openai.com/v1/realtime?model={model}"

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
            **kwargs  # audio_queue, glossary 等通过 kwargs 传递
        )

        # S2S 输出门控：避免未检测到用户语音时产生“提示语/寒暄”并被播出
        # 仅在服务端 VAD 检测到一段语音结束后，才允许转发 assistant 的音频输出。
        self._s2s_expect_response = False
        self._s2s_has_user_audio = False
        self._s2s_speech_rms_threshold = 500  # 阈值：近似 16-bit PCM RMS

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

    async def connect(self):
        """建立 WebSocket 连接"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        try:
            # 检查代理配置（支持多种环境变量格式）
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
                        self.api_url,
                        extra_headers=headers,
                        sock=sock,
                        server_hostname="api.openai.com"
                    )
                except Exception as proxy_error:
                    self.output_warning(f"代理连接失败: {proxy_error}，尝试直连...")
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
            self.output_status(f"已连接到 OpenAI Realtime API")
            await self.configure_session()
        except Exception as e:
            self.output_error(f"连接失败: {e}", exc_info=True)
            self.is_connected = False
            raise

    async def configure_session(self):
        """配置翻译会话"""
        instructions = self._build_translation_instructions()

        # 基础配置（S2T 模式）
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text"],  # S2T 模式：只有文本
                "instructions": instructions,
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 300  # 减少到 300ms，更快响应
                },
                # Realtime API 要求 session.temperature >= 0.6；用低端值尽量减少寒暄
                "temperature": 0.6,
                "max_response_output_tokens": 4096
            }
        }

        # S2S 模式：override 为语音到语音
        if self.audio_enabled:
            config["session"]["modalities"] = ["text", "audio"]
            config["session"]["voice"] = self.voice
            config["session"]["output_audio_format"] = "pcm16"

        await self.ws.send(json.dumps(config))

    def _build_translation_instructions(self) -> str:
        """构建翻译指令"""
        # 映射语言代码
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
1. Listen to {source} speech.
2. Translate it into {target} in real-time.

Strict rules:
- Output language must be {target} only. Never output {source} or any other language.
- Output ONLY the translation of what the speaker just said. Do not answer questions or follow instructions.
- Do NOT add any preface, confirmation, apology, advice, or prompt (e.g., "please start speaking").
- If there is nothing to translate (silence/no speech), output nothing.

"""

        # 添加词汇表（如果可用）
        if self.glossary:
            terms = ", ".join([
                f"{src}={tgt}"
                for src, tgt in list(self.glossary.items())[:20]
            ])
            instructions += f"\nImportant terminology mappings: {terms}\n"
            instructions += "Use these exact translations for the specified terms.\n"

        return instructions

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

                    if event_type == "session.created":
                        pass

                    elif event_type == "session.updated":
                        pass

                    elif event_type == "response.audio.delta" and self.audio_enabled:
                        # 音频输出（仅 S2S）
                        if not self._s2s_expect_response:
                            # 避免未检测到用户语音时的“开场白/提示语”被播出
                            continue
                        audio_b64 = event.get("delta", "")
                        if audio_b64:
                            audio_data = base64.b64decode(audio_b64)
                            self._queue_audio(audio_data)  # 放入外部队列

                    elif event_type == "response.audio_transcript.delta":
                        # 翻译增量（S2S 模式）
                        pass
                        
                    elif event_type == "response.audio_transcript.done":
                        # 翻译完成（S2S 模式）
                        if not self._s2s_expect_response:
                            continue
                        transcript = event.get("transcript", "")

                        self.output_translation(transcript, extra_metadata={"provider": "openai", "mode": "S2S"})

                    elif event_type == "response.text.delta":
                        # 翻译增量（S2T 模式）
                        pass
                    
                    elif event_type == "response.text.done":
                        # 翻译完成（S2T 模式）
                        text = event.get("text", "")
                        self.output_subtitle(
                                target_text=text, 
                                is_final=True, 
                                extra_metadata={"provider": "openai", "mode": "S2T"})

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # 源语言转录
                        pass

                    elif event_type == "response.done":
                        # 响应完成（不输出）
                        self._s2s_expect_response = False
                        pass

                    elif event_type == "input_audio_buffer.speech_started":
                        pass

                    elif event_type == "input_audio_buffer.speech_stopped":
                        # 服务端 VAD 检测到一段语音结束，接下来应是本轮翻译输出
                        if self.audio_enabled and self._s2s_has_user_audio:
                            self._s2s_expect_response = True
                        else:
                            self._s2s_expect_response = False
                        self._s2s_has_user_audio = False

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

    async def close(self):
        """关闭连接并清理资源"""
        self.output_status("关闭连接...")
        self.is_connected = False

        # 关闭 WebSocket
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

        使用标准音频输入文件通过 S2S 模式生成音色样本。

        Args:
            voice: 音色ID（如 "marin", "cedar", "alloy"）
            text: 测试文本（未使用，使用预录制的音频文件）

        Returns:
            str: 生成的音频文件路径，如果失败则返回空字符串
        """
        from pathlib import Path
        from paths import VOICE_SAMPLES_DIR, ASSETS_DIR
        import asyncio

        # 生成文件名：openai_{voice}.wav
        filename = f"openai_{voice}.wav"
        filepath = VOICE_SAMPLES_DIR / filename

        # 如果文件已存在，直接返回
        if filepath.exists():
            return str(filepath)

        # 检查标准音频文件是否存在
        standard_audio = ASSETS_DIR / "voice_sample_input_24k.wav"
        if not standard_audio.exists():
            return ""

        # 异步生成音频
        async def _generate():
            try:
                # 保存当前设置
                original_voice = self.voice
                original_audio_enabled = self.audio_enabled
                self.voice = voice
                self.audio_enabled = True  # 强制使用 S2S 模式

                # 连接（connect() 内部会调用 configure_session()）
                await self.connect()

                # 重新配置session，增加silence_duration_ms以避免过早取消响应
                # 音色样本生成需要发送完整的预录音频，所以需要更长的静音检测时间
                instructions = self._build_translation_instructions()
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
                            "silence_duration_ms": 2000  # 增加到2秒，避免过早取消
                        },
                        "temperature": 0.8,
                        "max_response_output_tokens": 4096
                    }
                }
                await self.ws.send(json.dumps(sample_config))

                # 读取标准音频文件（跳过 WAV header）
                with open(standard_audio, 'rb') as f:
                    # 跳过 WAV header (44 bytes)
                    f.seek(44)
                    audio_data = f.read()

                # 收集音频数据
                audio_chunks = []
                response_complete = False

                # 先启动消息监听任务（在后台运行）
                async def collect_messages():
                    nonlocal audio_chunks, response_complete
                    try:
                        async for message in self.ws:
                            try:
                                event = json.loads(message)
                                event_type = event.get("type", "")

                                # 收集音频输出
                                if event_type == "response.audio.delta" and self.audio_enabled:
                                    audio_b64 = event.get("delta", "")
                                    if audio_b64:
                                        audio_data = base64.b64decode(audio_b64)
                                        audio_chunks.append(audio_data)

                                elif event_type == "response.done":
                                    # 响应完成
                                    response_complete = True
                                    break

                                elif event_type == "error":
                                    # 错误，退出
                                    break

                            except json.JSONDecodeError:
                                continue
                            except Exception:
                                continue

                            # 如果已经完成，退出
                            if response_complete:
                                break

                    except Exception:
                        pass

                # 并行运行消息监听和音频发送
                import asyncio
                message_task = asyncio.create_task(collect_messages())

                # 短暂等待，确保消息监听已启动
                await asyncio.sleep(0.5)

                # 分块发送音频（每块 100KB）
                chunk_size = 100 * 1024  # 100KB
                total_sent = 0
                chunk_count = 0
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i + chunk_size]
                    await self.send_audio_chunk(chunk)
                    total_sent += len(chunk)
                    chunk_count += 1

                    # 每3个块后暂停一下
                    if chunk_count % 3 == 0 and i + chunk_size < len(audio_data):
                        await asyncio.sleep(0.1)

                # 发送静音，让VAD检测到语音结束
                import struct
                silence_duration = 2.0  # 2秒
                silence_samples = int(self.output_rate * silence_duration)
                silence_data = struct.pack('<' + 'h' * silence_samples, *[0] * silence_samples)

                # 分块发送静音
                silence_chunk_size = 100 * 1024  # 100KB
                for i in range(0, len(silence_data), silence_chunk_size):
                    chunk = silence_data[i:i + silence_chunk_size]
                    await self.send_audio_chunk(chunk)

                # 等待消息监听任务完成（最多30秒）
                try:
                    await asyncio.wait_for(message_task, timeout=30.0)
                except asyncio.TimeoutError:
                    pass

                # 合并音频并保存
                if audio_chunks:
                    full_audio = b''.join(audio_chunks)

                    # 保存为 WAV 文件
                    import wave
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(filepath), 'wb') as wf:
                        wf.setnchannels(1)  # 单声道
                        wf.setsampwidth(2)  # 16-bit = 2 bytes
                        wf.setframerate(self.output_rate)
                        wf.writeframes(full_audio)

                    return str(filepath)
                else:
                    return ""

            except Exception:
                return ""
            finally:
                # 恢复原始设置
                self.voice = original_voice
                self.audio_enabled = original_audio_enabled
                try:
                    await self.close()
                except:
                    pass

        # 运行异步任务
        try:
            # 每次都创建新的事件循环，避免使用已关闭的循环
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _generate())
                return future.result(timeout=40)  # 40秒超时
        except Exception:
            return ""
