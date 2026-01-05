"""
阿里云 Qwen LiveTranslate 统一客户端
支持 S2S (语音到语音) 和 S2T (语音到文本) 两种模式
"""

import os
import time
import base64
import asyncio
import json
import websockets
from typing import Dict, Optional
try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio

import queue
import threading
import logging

# 导入基础类和 mixins
from translation_client_base import BaseTranslationClient, TranslationProvider
from client_output_mixin import OutputMixin
from client_audio_mixin import AudioPlayerMixin

logger = logging.getLogger(__name__)


def load_glossary(glossary_file=None):
    """
    加载词汇表

    Args:
        glossary_file: 词汇表文件路径，默认使用 glossary.json

    Returns:
        词汇表字典
    """
    if glossary_file is None:
        # 默认使用当前目录下的 glossary.json
        current_dir = os.path.dirname(__file__)
        glossary_file = os.path.join(current_dir, "glossary.json")

    if os.path.exists(glossary_file):
        try:
            with open(glossary_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("glossary", {})
        except Exception as e:
            logger.warning(f"加载词汇表失败: {e}")

    # 返回默认词汇表
    return {
        "示例公司": "Example Company",
        "张总": "Mr. Zhang",
        "核心产品": "Core Product",
        "业务系统": "Business System"
    }


def build_translation_instructions(glossary):
    """
    构建翻译指令（极简版本）

    Args:
        glossary: 词汇表字典

    Returns:
        instructions 字符串
    """
    # 使用紧凑的单行格式，避免多行列表被误解为需要输出的内容
    terms = "/n".join([f"【{zh}:{en}】" for zh, en in glossary.items()])

    instructions = f"""常用词表: {terms}. """
    return instructions


class QwenClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
    """
    阿里云 Qwen LiveTranslate 客户端

    支持 S2S 和 S2T 两种模式：
    - S2S (audio_enabled=True): 语音输入 → 翻译 → 语音输出
    - S2T (audio_enabled=False): 语音输入 → 翻译 → 文本输出
    """

    # 类属性，用于识别 provider
    provider = TranslationProvider.ALIYUN

    # 支持的音色列表（来源：阿里云官方文档）
    SUPPORTED_VOICES = {
        "cherry": "Cherry (女声)",
        "nofish": "Nofish (男声)",
    }

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: Optional[str] = "cherry",
        audio_enabled: bool = True,
        glossary_file: Optional[str] = None,
        **kwargs
    ):
        """
        初始化 Qwen 翻译客户端

        Args:
            api_key: 阿里云 API Key
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            voice: 音色选择 (cherry/nofish)，仅 S2S 模式有效
            audio_enabled: 是否启用音频输出（True=S2S, False=S2T）
            glossary_file: 词汇表文件路径（可选）
            **kwargs: 其他参数
        """
        if not api_key:
            raise ValueError("API key cannot be empty.")

        # 调用父类 __init__ (cooperative multiple inheritance)
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            glossary_file=glossary_file,
            **kwargs
        )

        # WebSocket 连接
        self.ws = None
        self.api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-livetranslate-flash-realtime"

        # 加载词汇表
        self.glossary = load_glossary(glossary_file)
        self.output_debug(f"已加载词汇表，包含 {len(self.glossary)} 个术语")

        # 麦克风输入配置（S2S 和 S2T 都需要）
        self._input_rate = 16000
        self._input_chunk = 1600  # 100ms @ 16kHz
        self._input_format = pyaudio.paInt16
        self._input_channels = 1

        # PyAudio 实例
        self._pyaudio_instance = pyaudio.PyAudio()

    @property
    def input_rate(self) -> int:
        """输入采样率（麦克风）"""
        return self._input_rate

    @property
    def output_rate(self) -> int:
        """输出采样率（仅 S2S）"""
        return 24000

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """获取支持的音色列表"""
        return cls.SUPPORTED_VOICES.copy()

    async def connect(self):
        """建立 WebSocket 连接"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            self.ws = await websockets.connect(
                self.api_url,
                extra_headers=headers
            )
            self.is_connected = True
            self.output_status(f"已连接到阿里云 Qwen LiveTranslate 服务")
            await self.configure_session()
        except Exception as e:
            self.output_error(f"连接失败: {e}", exc_info=True)
            self.is_connected = False
            raise

    async def configure_session(self):
        """配置翻译会话"""
        # 根据 audio_enabled 设置 modalities
        modalities = ["text", "audio"] if self.audio_enabled else ["text"]

        # 基础配置（S2T 模式）
        config = {
            "event_id": f"event_{int(time.time() * 1000)}",
            "type": "session.update",
            "session": {
                "modalities": modalities,
                "voice": self.voice if self.audio_enabled else "cherry",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16" if self.audio_enabled else None,
                "translation": {
                    "language": self.target_language,
                    "instructions": build_translation_instructions(self.glossary),
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800
                },
            }
        }

        # S2S 模式：添加音频输出参数
        if self.audio_enabled:
            config["session"]["audio"] = {
                # 注意：rate 参数已确认无效，已移除
                "pitch": 1.0,
                "volume": 50
            }

        self.output_debug(f"会话配置完成 (模式: {'S2S' if self.audio_enabled else 'S2T'})")
        await self.ws.send(json.dumps(config))

    async def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块"""
        if not self.is_connected:
            return

        event = {
            "event_id": f"event_{int(time.time() * 1000)}",
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(audio_data).decode()
        }
        await self.ws.send(json.dumps(event))

    def start_audio_player(self):
        """启动音频播放器（仅 S2S 模式）"""
        if not self.audio_enabled:
            return  # S2T 模式，不启动音频播放

        super().start_audio_player()

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息"""
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type == "response.audio.delta" and self.audio_enabled:
                    # 音频增量数据（仅 S2S）
                    audio_b64 = event.get("delta", "")
                    if audio_b64:
                        audio_data = base64.b64decode(audio_b64)
                        self.queue_audio(audio_data)

                elif event_type == "response.done":
                    # 响应完成
                    usage = event.get("response", {}).get("usage", {})
                    if usage:
                        self.output_debug(f"Token 使用: {json.dumps(usage)}")

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # 源语言转录完成
                    transcript = event.get("transcript", "")
                    if transcript:
                        self.output_debug(f"[源语言] {transcript}")

                elif event_type == "conversation.item.input_audio_transcription.failed":
                    # 源语言转录失败
                    error = event.get("error", {})
                    self.output_warning(f"源语言转录失败: {error.get('message', 'Unknown error')}")

                elif event_type == "translation.part":
                    # 翻译增量（流式）
                    text = event.get("text", "")
                    if text:
                        # 使用 partial 模式显示增量翻译
                        self.output_translation(text, is_final=False)

                elif event_type == "translation.done":
                    # 翻译完成（最终结果）
                    text = event.get("text", "")
                    if text:
                        self.output_translation(text, is_final=True)

                elif event_type == "error":
                    # 错误消息
                    error_message = event.get("error", {}).get("message", "Unknown error")
                    self.output_error(f"服务器错误: {error_message}")

        except websockets.exceptions.ConnectionClosed:
            self.output_warning("WebSocket 连接已关闭")
        except Exception as e:
            self.output_error(f"处理服务器消息时出错: {e}", exc_info=True)

    async def start_microphone_streaming(self):
        """开始麦克风音频流式传输（示例方法）"""
        stream = self._pyaudio_instance.open(
            format=self._input_format,
            channels=self._input_channels,
            rate=self._input_rate,
            input=True,
            frames_per_buffer=self._input_chunk,
        )

        self.output_status("开始麦克风音频流式传输...")

        try:
            while self.is_connected:
                try:
                    audio_chunk = stream.read(self._input_chunk, exception_on_overflow=False)
                    await self.send_audio_chunk(audio_chunk)
                except Exception as e:
                    self.output_error(f"读取麦克风数据失败: {e}")
                    break
        finally:
            stream.stop_stream()
            stream.close()

    async def close(self):
        """关闭连接并清理资源"""
        self.is_connected = False

        # 停止音频播放器
        self.stop_audio_player()

        # 关闭 WebSocket 连接
        if self.ws:
            await self.ws.close()

        # 清理 PyAudio
        if self._pyaudio_instance:
            self._pyaudio_instance.terminate()

        self.output_status("连接已关闭")
