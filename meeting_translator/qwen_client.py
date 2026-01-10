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

# 导入基础类（已包含 OutputMixin）
from translation_client_base import BaseTranslationClient, TranslationProvider
# 导入统一的输出管理器
from output_manager import Out


def build_translation_instructions(glossary: Dict[str, str]) -> str:
    """
    构建翻译指令（极简版本）

    Args:
        glossary: 词汇表字典

    Returns:
        instructions 字符串
    """
    if not glossary:
        return ""

    # 使用紧凑的单行格式，避免多行列表被误解为需要输出的内容
    terms = "/n".join([f"【{zh}:{en}】" for zh, en in glossary.items()])

    instructions = f"""常用词表: {terms}. """
    return instructions


class QwenClient(BaseTranslationClient):
    """
    阿里云 Qwen LiveTranslate 客户端

    支持 S2S 和 S2T 两种模式：
    - S2S (audio_enabled=True): 语音输入 → 翻译 → 语音输出
    - S2T (audio_enabled=False): 语音输入 → 翻译 → 文本输出

    继承自 BaseTranslationClient，已包含：
    - OutputMixin: 统一的输出接口
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
        **kwargs  # audio_queue, glossary 等通过 kwargs 传递给父类
    ):
        """
        初始化 Qwen 翻译客户端

        Args:
            api_key: 阿里云 API Key
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            voice: 音色选择 (cherry/nofish)，仅 S2S 模式有效
            audio_enabled: 是否启用音频输出（True=S2S, False=S2T）
            **kwargs: 其他参数（audio_queue, glossary 等传递给父类）
        """
        if not api_key:
            raise ValueError("API key cannot be empty.")

        # 调用父类 __init__
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=voice,
            audio_enabled=audio_enabled,
            **kwargs  # audio_queue, glossary 等通过 kwargs 传递
        )

        # WebSocket 连接
        self.ws = None
        self.api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-livetranslate-flash-realtime"

        # 麦克风输入配置（S2S 和 S2T 都需要）
        self._input_rate = 16000
        self._input_chunk = 1600  # 100ms @ 16kHz
        self._input_format = pyaudio.paInt16
        self._input_channels = 1

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
        # 基础配置（S2T 模式）
        config = {
            "event_id": f"event_{int(time.time() * 1000)}",
            "type": "session.update",
            "session": {
                "modalities": ["text"],  # S2T 模式：只有文本
                "input_audio_format": "pcm16",
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

        # S2S 模式：override 为语音到语音
        if self.audio_enabled:
            config["session"]["modalities"] = ["text", "audio"]
            config["session"]["voice"] = self.voice
            config["session"]["output_audio_format"] = "pcm16"
            config["session"]["audio"] = {
                # 注意：rate 参数已确认无效，已移除
                "pitch": 1.0,
                "volume": 50
            }

        await self.ws.send(json.dumps(config))

    async def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块"""
        if not self.is_connected:
            return

        try:
            event = {
                "event_id": f"event_{int(time.time() * 1000)}",
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_data).decode()
            }
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.output_error(f"发送音频块失败: {e}")

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息"""
        # S2T 模式：维护当前句子的全量文本
        self._current_sentence = ""
        self._current_predicted = ""

        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type == "response.audio.delta" and self.audio_enabled:
                    # 音频增量数据（仅 S2S）
                    audio_b64 = event.get("delta", "")
                    if audio_b64:
                        audio_data = base64.b64decode(audio_b64)
                        self._queue_audio(audio_data)  # 放入外部队列

                elif event_type == "response.done":
                    # 响应完成（不输出）
                    pass

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # 源语言转录完成（不输出，避免冗余）
                    pass

                elif event_type == "response.audio_transcript.done":
                    # 目标语言翻译完成（S2S 模式的翻译文本）
                    transcript = event.get("transcript", "")
                    if transcript:
                        self.output_translation(transcript, extra_metadata={"provider": "aliyun", "mode": "S2S"})
                        

                elif event_type == "response.text.text" and not self.audio_enabled:
                    # S2T 模式：非最终更新
                    text = event.get("text", "")
                    predicted = event.get("stash", "")  # Qwen 的预测文本

                    if text:
                        # 更新全量文本（Qwen 是 replace 模式）
                        self._current_sentence = text
                        self._current_predicted = predicted if predicted else ""

                        # 发送临时字幕（包含预测文本）
                        self.output_subtitle(
                            target_text=self._current_sentence, 
                            is_final=False,
                            predicted_text=self._current_predicted,
                            extra_metadata={"provider": "aliyun", "mode": "S2T"})
                            

                elif event_type == "response.text.done" and not self.audio_enabled:
                    # S2T 模式：翻译完成
                    response_data = event.get("response", {})
                    text = response_data.get("text", "")

                    # 如果顶层也有 text 字段，优先使用
                    if not text:
                        text = event.get("text", "")

                    if text:
                        # 更新最终全量文本
                        self._current_sentence = text
                        self._current_predicted = ""

                        # 发送最终字幕
                        self.output_subtitle(
                            target_text=self._current_sentence,
                            is_final=True,
                            extra_metadata={"provider": "aliyun", "mode": "S2T"})
                        
                        # 重置
                        self._current_sentence = ""
                    else:
                        self.output_warning("[S2T Done] 事件中没有找到翻译文本")

                elif event_type == "conversation.item.input_audio_transcription.failed":
                    # 源语言转录失败
                    error = event.get("error", {})
                    self.output_warning(f"源语言转录失败: {error.get('message', 'Unknown error')}")

                elif event_type == "error":
                    # 错误消息
                    error_message = event.get("error", {}).get("message", "Unknown error")
                    self.output_error(f"服务器错误: {error_message}")

        except websockets.exceptions.ConnectionClosed:
            self.output_warning("WebSocket 连接已关闭")
        except Exception as e:
            self.output_error(f"处理服务器消息时出错: {e}", exc_info=True)

    async def close(self):
        """关闭连接并清理资源"""
        self.is_connected = False

        # 关闭 WebSocket 连接
        if self.ws:
            await self.ws.close()

        self.output_status("连接已关闭")
