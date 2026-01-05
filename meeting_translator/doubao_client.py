"""
Doubao (ByteDance) Real-time Translation Client
Implements real-time speech-to-speech and speech-to-text translation
using Doubao's AST (Automatic Simultaneous Translation) API

音色说明：豆包使用语音克隆技术，自动复制说话人音色，无需选择音色
"""

import os
import sys
import uuid
import asyncio
import websockets
from websockets import Headers
from typing import Dict, Optional
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio

# 导入基础类和 mixins
from translation_client_base import BaseTranslationClient, TranslationProvider
from client_output_mixin import OutputMixin
from client_audio_mixin import AudioPlayerMixin

# Add python_protogen to path for protobuf imports
current_dir = os.path.dirname(os.path.abspath(__file__))
protogen_dir = os.path.join(current_dir, "python_protogen")
if protogen_dir not in sys.path:
    sys.path.insert(0, protogen_dir)

# Try to import protobuf dependencies (required for Doubao)
try:
    from python_protogen.products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
    from python_protogen.common.events_pb2 import Type
    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False
    TranslateRequest = None
    TranslateResponse = None
    Type = None


class DoubaoClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
    """
    豆包 AST 客户端（语音克隆技术）

    支持 S2S 和 S2T 两种模式：
    - S2S (audio_enabled=True): 语音输入 → 翻译 → 语音输出（克隆说话人音色）
    - S2T (audio_enabled=False): 语音输入 → 翻译 → 文本输出

    音色说明：
    - 使用语音克隆技术，自动复制说话人音色
    - 不支持手动选择音色
    - 不支持音色试听功能
    """

    # 类属性，用于识别 provider
    provider = TranslationProvider.DOUBAO

    # 豆包 AST API 使用 16kHz
    AUDIO_RATE = 16000

    # 事件类型常量
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
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        audio_enabled: bool = True,
        glossary: Optional[Dict[str, str]] = None,
        access_token: Optional[str] = None,
        **kwargs
    ):
        """
        初始化豆包翻译客户端

        Args:
            api_key: 豆包 App ID (doubao_app_id)
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            audio_enabled: 是否启用音频输出（True=S2S, False=S2T）
            glossary: 词汇表字典（可选）
            access_token: 豆包 Access Token (doubao_access_token)
            **kwargs: 其他参数

        Note:
            豆包使用语音克隆技术，自动复制说话人音色，因此没有 voice 参数。

            glossary 应该由主程序加载后传入，client 只负责使用。

            依赖检查：需要安装 protobuf 库
            pip install protobuf
        """
        # 检查依赖
        is_available, error_msg = self.check_dependencies()
        if not is_available:
            raise ImportError(error_msg)

        if not api_key:
            raise ValueError("API key (doubao_app_id) cannot be empty.")

        # 调用父类 __init__ (注意：不传 voice 参数)
        super().__init__(
            api_key=api_key,
            source_language=source_language,
            target_language=target_language,
            voice=None,  # 豆包不支持选择音色（语音克隆）
            audio_enabled=audio_enabled,
            **kwargs
        )

        # 豆包特定配置
        self.app_key = api_key  # doubao_app_id
        self.access_key = access_token  # doubao_access_token
        self.ws_url = "wss://openspeech.bytedance.com/api/v4/ast/v2/translate"
        self.resource_id = "volc.service_type.10053"

        self.ws = None
        self.session_id = None

        # 词汇表（由主程序传入）
        self.glossary = glossary or {}
        if self.glossary:
            self.output_debug(f"已加载词汇表，包含 {len(self.glossary)} 个术语")

        # 音频配置（16kHz）
        self._input_rate = self.AUDIO_RATE
        self._input_chunk = 1600  # 100ms @ 16kHz
        self._input_format = pyaudio.paInt16
        self._input_channels = 1

        # PyAudio 实例
        self._pyaudio_instance = pyaudio.PyAudio() if audio_enabled else None

    @property
    def input_rate(self) -> int:
        """输入采样率（麦克风）"""
        return self._input_rate

    @property
    def output_rate(self) -> int:
        """输出采样率（仅 S2S）"""
        return 16000  # 豆包只支持 16000 或 48000

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        获取支持的音色列表

        Returns:
            空字典（豆包不支持手动选择音色）

        Note:
            豆包使用语音克隆技术，自动复制说话人音色，
            因此不支持手动选择音色。
        """
        return {}

    def supports_voice_testing(self) -> bool:
        """
        检查是否支持音色试听功能

        Returns:
            False（豆包不支持音色试听）
        """
        return False

    @staticmethod
    def check_dependencies() -> tuple[bool, str]:
        """
        检查豆包依赖是否已安装

        Returns:
            (is_available, error_message)
            - is_available: True 如果所有依赖都满足
            - error_message: 依赖缺失时的错误消息
        """
        if not PROTOBUF_AVAILABLE:
            return False, "豆包 API 需要 protobuf 依赖包。请运行: pip install protobuf"

        return True, ""

    async def connect(self):
        """建立 WebSocket 连接"""
        if self.is_connected:
            self.output_warning("已经连接到豆包 API")
            return

        try:
            # 生成连接 ID
            conn_id = str(uuid.uuid4())

            # 构建请求头
            headers = Headers({
                "X-Api-App-Key": self.app_key,
                "X-Api-Access-Key": self.access_key,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Connect-Id": conn_id
            })

            # 建立 WebSocket 连接
            self.ws = await websockets.connect(
                self.ws_url,
                extra_headers=headers,
                max_size=1000000000,
                ping_interval=None
            )

            log_id = self.ws.response_headers.get('X-Tt-Logid', 'N/A')
            self.output_status(f"已连接到豆包 API (log_id={log_id})")

            self.is_connected = True

            # 连接后配置会话
            await self.configure_session()

        except Exception as e:
            self.output_error(f"豆包连接失败: {e}", exc_info=True)
            raise

    async def configure_session(self):
        """配置翻译会话"""
        if not self.is_connected:
            raise Exception("必须先连接才能配置会话")

        try:
            # 生成会话 ID
            self.session_id = str(uuid.uuid4())

            # 发送 StartSession 请求
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.StartSession
            request.user.uid = "meeting_translator"
            request.user.did = "meeting_translator"

            # 源音频配置
            request.source_audio.format = "wav"
            request.source_audio.rate = self.input_rate
            request.source_audio.bits = 16
            request.source_audio.channel = 1

            # 基础配置（S2T 模式）
            request.request.mode = "s2t"
            request.request.source_language = self.source_language
            request.request.target_language = self.target_language

            # S2S 模式：override 为语音到语音
            if self.audio_enabled:
                request.request.mode = "s2s"
                request.target_audio.format = "pcm"  # PCM 格式直接播放
                request.target_audio.rate = self.output_rate
                request.target_audio.bits = 16
                request.target_audio.channel = 1

            # 配置词汇表
            if self.glossary:
                # 设置 glossary_list (map<string, string>)
                for source_term, target_term in self.glossary.items():
                    request.request.corpus.glossary_list[source_term] = target_term
                self.output_debug(f"已加载 {len(self.glossary)} 个词汇表术语到豆包 corpus")

            await self.ws.send(request.SerializeToString())

            # 等待 SessionStarted 响应
            message = await self.ws.recv()
            response = TranslateResponse()
            response.ParseFromString(message)

            if response.event != Type.SessionStarted:
                raise Exception(
                    f"会话启动失败: event={response.event}, "
                    f"message={response.response_meta.Message}"
                )

            mode_str = "S2S" if self.audio_enabled else "S2T"
            self.output_debug(f"豆包会话已配置 (ID={self.session_id}, mode={mode_str})")

        except Exception as e:
            self.output_error(f"豆包会话配置失败: {e}", exc_info=True)
            raise

    async def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块"""
        if not self.is_connected or not self.ws:
            self.output_warning("未连接，无法发送音频")
            return

        try:
            request = TranslateRequest()
            request.request_meta.SessionID = self.session_id
            request.event = Type.TaskRequest
            request.source_audio.binary_data = audio_data

            await self.ws.send(request.SerializeToString())

        except Exception as e:
            self.output_error(f"发送音频块失败: {e}")
            self.is_connected = False

    def start_audio_player(self):
        """启动音频播放器（仅 S2S 模式）"""
        if not self.audio_enabled:
            return  # S2T 模式，不启动音频播放

        super().start_audio_player()

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息"""
        try:
            while self.is_connected:
                message = await self.ws.recv()
                response = TranslateResponse()
                response.ParseFromString(message)
                event_type = response.event

                # 源语言识别（ASR）
                if event_type == self.EVENT_ASR_DELTA:
                    # 源语言增量识别
                    source_text = response.text
                    if source_text:
                        self.output_debug(f"[源语言] {source_text}")

                elif event_type == self.EVENT_ASR_DONE:
                    # 源语言识别完成
                    source_text = response.text
                    if source_text:
                        self.output_debug(f"[源语言完成] {source_text}")

                # 翻译增量（跳过显示）
                elif event_type == self.EVENT_TRANSLATE_DELTA:
                    # 翻译增量文本（跳过，只显示最终结果）
                    pass

                # 翻译完成
                elif event_type == self.EVENT_TRANSLATE_DONE:
                    target_text = response.text
                    if target_text:
                        self.output_translation(target_text, is_final=True)

                # 音频输出（仅 S2S）
                elif event_type == self.EVENT_AUDIO_DELTA and self.audio_enabled:
                    # 音频增量数据
                    audio_data = response.target_audio.binary_data
                    if audio_data:
                        self.queue_audio(audio_data)

                elif event_type == self.EVENT_AUDIO_DONE and self.audio_enabled:
                    self.output_debug("音频输出完成")

                # 计费信息
                elif event_type == self.EVENT_USAGE:
                    self.output_debug(f"计费信息: {response}")

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

        # 停止音频播放器
        self.stop_audio_player()

        # 关闭 WebSocket
        if self.ws:
            try:
                await self.ws.close()
                self.output_debug("WebSocket 已关闭")
            except Exception as e:
                self.output_warning(f"关闭 WebSocket 时出错: {e}")

        # 清理 PyAudio
        if self._pyaudio_instance:
            try:
                self._pyaudio_instance.terminate()
                self.output_debug("PyAudio 已终止")
            except Exception as e:
                self.output_warning(f"终止 PyAudio 时出错: {e}")
