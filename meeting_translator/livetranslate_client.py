"""
阿里云官方 LiveTranslateClient 实现
基于 Qwen3-LiveTranslate-Flash-Realtime
"""

import os
import time
import base64
import asyncio
import json
import websockets
try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    # 如果没有安装 PyAudioWPatch，使用标准 PyAudio
    import pyaudio
import queue
import threading
import traceback


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
            print(f"[WARN] 加载词汇表失败: {e}")

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


def build_corpus_text(glossary):
    """
    构建 corpus.text（用于提高识别准确度）

    Args:
        glossary: 词汇表字典

    Returns:
        corpus text 字符串
    """
    # 只提取中文术语，不添加任何背景信息或示例
    chinese_terms = list(glossary.keys())

    # 简单的词汇列表，用顿号分隔（更符合中文习惯）
    context = "、".join(chinese_terms)

    return context


class LiveTranslateClient:
    """阿里云实时翻译客户端（官方实现）"""

    def __init__(
        self,
        api_key: str,
        source_language: str = "zh",
        target_language: str = "en",
        voice: str | None = "Cherry",
        *,
        audio_enabled: bool = True,
        glossary_file: str = None
    ):
        """
        初始化翻译客户端

        Args:
            api_key: 阿里云 API Key
            source_language: 源语言 (zh/en/ja/ko/...)
            target_language: 目标语言 (en/zh/ja/ko/...)
            voice: 语音选择 (Cherry/Bella/Alice)
            audio_enabled: 是否启用音频输出
            glossary_file: 词汇表文件路径（可选）
        """
        if not api_key:
            raise ValueError("API key cannot be empty.")

        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.audio_enabled = audio_enabled
        self.voice = voice if audio_enabled else "Cherry"
        self.ws = None
        self.api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-livetranslate-flash-realtime"

        # 加载词汇表
        self.glossary = load_glossary(glossary_file)
        print(f"[OK] 已加载词汇表，包含 {len(self.glossary)} 个术语")

        # 麦克风输入配置
        self.input_rate = 16000
        self.input_chunk = 1600  # 100ms @ 16kHz
        self.input_format = pyaudio.paInt16
        self.input_channels = 1

        # 扬声器输出配置
        self.output_rate = 24000  # 重要：24kHz 输出
        self.output_chunk = 2400  # 100ms @ 24kHz
        self.output_format = pyaudio.paInt16
        self.output_channels = 1

        # 状态管理
        self.is_connected = False
        self.audio_player_thread = None
        self.audio_playback_queue = queue.Queue()
        self.pyaudio_instance = pyaudio.PyAudio()

    async def connect(self):
        """建立 WebSocket 连接"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            self.ws = await websockets.connect(
                self.api_url,
                extra_headers=headers
            )
            self.is_connected = True
            print(f"[OK] 已连接到: {self.api_url}")
            await self.configure_session()
        except Exception as e:
            print(f"[ERROR] 连接失败: {e}")
            self.is_connected = False
            raise

    async def configure_session(self):
        """配置翻译会话"""
        config = {
            "event_id": f"event_{int(time.time() * 1000)}",
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"] if self.audio_enabled else ["text"],
                "voice": self.voice,  # 总是包含 voice（即使未启用音频）
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                # 暂时移除 corpus.text，仅使用 instructions
                # "input_audio_transcription": {
                #     "language": self.source_language,
                #     "corpus": {
                #         "text": build_corpus_text(self.glossary)
                #     }
                # },
                "translation": {
                    "language": self.target_language
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800
                },
                # TTS 控制参数
                "rate": 4,  # 加快语速
                "pitch": 1.0,
                "volume": 50
            }
        }
        print(f"[OK] Session 配置完成")
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

    def _audio_player_task(self):
        """音频播放器线程任务（官方实现 + 优雅关闭）"""
        stream = self.pyaudio_instance.open(
            format=self.output_format,
            channels=self.output_channels,
            rate=self.output_rate,
            output=True,
            frames_per_buffer=self.output_chunk,
        )
        print("[OK] 音频播放器已启动（24kHz, 单声道）")

        try:
            while self.is_connected or not self.audio_playback_queue.empty():
                try:
                    audio_chunk = self.audio_playback_queue.get(timeout=0.1)
                    if audio_chunk is None:  # 终止信号
                        break
                    stream.write(audio_chunk)
                    self.audio_playback_queue.task_done()
                except queue.Empty:
                    continue
        finally:
            # 优雅关闭：先清空剩余队列，避免"啪"声
            try:
                while not self.audio_playback_queue.empty():
                    leftover = self.audio_playback_queue.get_nowait()
                    if leftover is not None:
                        stream.write(leftover)
                    self.audio_playback_queue.task_done()
            except queue.Empty:
                pass

            # 等待硬件缓冲区播放完毕，避免截断
            time.sleep(0.1)

            stream.stop_stream()
            stream.close()
            print("[OK] 音频播放器已停止")

    def start_audio_player(self):
        """启动音频播放器线程"""
        if not self.audio_enabled:
            return

        if self.audio_player_thread is None or not self.audio_player_thread.is_alive():
            self.audio_player_thread = threading.Thread(
                target=self._audio_player_task,
                daemon=True
            )
            self.audio_player_thread.start()

    async def handle_server_messages(self, on_text_received=None):
        """处理服务器消息（官方实现）"""
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type == "response.audio.delta" and self.audio_enabled:
                    # 音频增量数据
                    audio_b64 = event.get("delta", "")
                    if audio_b64:
                        audio_data = base64.b64decode(audio_b64)
                        self.audio_playback_queue.put(audio_data)

                elif event_type == "response.done":
                    # 响应完成
                    print("\n[OK] 响应完成")
                    usage = event.get("response", {}).get("usage", {})
                    if usage:
                        print(f"[INFO] Token 使用: {json.dumps(usage)}")

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # 源语言转录完成（输入音频的转录）
                    text = event.get("transcript", "")
                    language = event.get("language", "")
                    if text:
                        print(f"\n[源语言] {text} (语言: {language})")
                        if on_text_received:
                            on_text_received(f"[源] {text}")

                elif event_type == "response.audio_transcript.done":
                    # 目标语言文本（翻译结果）
                    text = event.get("transcript", "")
                    if text:
                        print(f"[目标语言] {text}")
                        if on_text_received:
                            on_text_received(f"[译] {text}")

                elif event_type == "conversation.item.input_audio_transcription.text":
                    # 源语言转录增量（实时显示转录过程）
                    text = event.get("text", "")
                    stash = event.get("stash", "")
                    if stash:
                        # stash 是预测部分
                        display_text = f"{text}{stash}"
                        print(f"[转录中] {display_text}", end="\r", flush=True)

                elif event_type == "error":
                    error = event.get("error", {})
                    error_code = error.get("code", "Unknown")
                    error_msg = error.get("message", "Unknown error")
                    print(f"\n[ERROR] {error_code}: {error_msg}")

                    # InternalError 通常表示会话失效，需要重连
                    if error_code == "InternalError":
                        print("[WARN] 检测到 InternalError，连接可能已失效")
                        self.is_connected = False
                        break  # 退出消息循环，让上层重连

        except websockets.exceptions.ConnectionClosed as e:
            print(f"\n[WARN] 连接已关闭: {e}")
            self.is_connected = False
        except Exception as e:
            print(f"\n[ERROR] 消息处理错误: {e}")
            traceback.print_exc()
            self.is_connected = False

    async def start_microphone_streaming(self):
        """启动麦克风流式传输（官方实现）"""
        stream = self.pyaudio_instance.open(
            format=self.input_format,
            channels=self.input_channels,
            rate=self.input_rate,
            input=True,
            frames_per_buffer=self.input_chunk
        )
        print("[OK] 麦克风已启动，请开始说话...")

        try:
            while self.is_connected:
                audio_chunk = await asyncio.get_event_loop().run_in_executor(
                    None, stream.read, self.input_chunk
                )
                await self.send_audio_chunk(audio_chunk)
        finally:
            stream.stop_stream()
            stream.close()
            print("[OK] 麦克风已停止")

    async def close(self):
        """优雅地关闭连接和清理资源"""
        self.is_connected = False

        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=2.0)
                print("[OK] WebSocket 已关闭")
            except asyncio.TimeoutError:
                print("[WARN] WebSocket 关闭超时")
            except Exception as e:
                print(f"[WARN] 关闭 WebSocket 时出错: {e}")

        # 优雅地停止音频播放器
        if self.audio_player_thread and self.audio_player_thread.is_alive():
            self.audio_playback_queue.put(None)  # 发送终止信号
            # 等待最多2秒，让播放器有时间清空队列和缓冲区
            self.audio_player_thread.join(timeout=2.0)
            if self.audio_player_thread.is_alive():
                print("[WARN] 音频播放器线程未能正常结束")

        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
                print("[OK] PyAudio 已终止")
            except Exception as e:
                print(f"[WARN] 终止 PyAudio 时出错: {e}")
