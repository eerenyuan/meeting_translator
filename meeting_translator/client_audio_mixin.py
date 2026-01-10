"""
Audio Player Mixin
提供音频播放能力给 translation clients (S2S 模式)
"""

from typing import Dict, Optional
import asyncio
from threading import Thread
import queue


class AudioPlayerMixin:
    """
    Translation Client 音频播放混入类

    为需要语音输出的 translation clients 提供：
    - 音频播放线程管理
    - 音色选择
    - 音频队列管理
    - 输出采样率配置
    - 音色试听功能

    使用方法：
        class MyS2SClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
            def __init__(self, voice="zhichu", **kwargs):
                super().__init__(voice=voice, **kwargs)
    """

    def __init__(self, *args, voice: Optional[str] = None, audio_enabled: bool = True, **kwargs):
        """
        初始化音频播放相关属性

        Args:
            voice: 音色选择（provider-specific，如 "zhichu", "alloy"）
            audio_enabled: 是否启用音频输出（默认 True）
            *args: 传递给父类的位置参数
            **kwargs: 传递给父类的关键字参数

        Raises:
            ValueError: 如果 audio_enabled=False 但提供了 voice 参数
        """
        # 参数验证：S2T 模式不应该有 audio 相关参数
        if not audio_enabled and voice is not None:
            raise ValueError(
                f"audio_enabled=False (S2T 模式) 不应该指定 voice 参数。"
                f"请移除 voice='{voice}' 或设置 audio_enabled=True。"
            )

        # 音频相关配置
        self.voice = voice if audio_enabled else None
        self.audio_enabled = audio_enabled

        # 音频播放线程
        self._audio_thread: Optional[Thread] = None
        self.__audio_queue: Optional[queue.Queue] = None  # 私有队列（完全封装）
        self._stop_audio_event: Optional[asyncio.Event] = None

        # 音频回调列表（用于转发音频数据到外部，如虚拟麦克风）
        self._audio_callbacks: list = []

        # 调用下一个类的 __init__ (cooperative inheritance)
        super().__init__(*args, **kwargs)

    @property
    def output_rate(self) -> int:
        """
        Get output audio sample rate

        Returns:
            Sample rate in Hz for audio playback (e.g., 24000)

        Note:
            Subclass should override this to provide provider-specific rate.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 output_rate property"
        )

    @classmethod
    def get_supported_voices(cls) -> Dict[str, str]:
        """
        Get supported voices for this provider

        Returns:
            Dict mapping voice IDs to display names
            Example: {"zhichu": "知楚 (女声)", "zhiyan": "知燕 (女声)"}

        Note:
            Subclass should override this to provide provider-specific voices.
        """
        return {}

    def start_audio_player(self):
        """
        启动音频播放线程

        创建后台线程来播放接收到的音频数据。
        线程会从内部队列获取音频数据并播放。
        """
        if self._audio_thread is not None and self._audio_thread.is_alive():
            # 音频播放线程已在运行
            return

        import pyaudio

        self.__audio_queue = queue.Queue()
        self._stop_audio_event = asyncio.Event()

        def audio_player_loop():
            """音频播放循环（在单独的线程中运行）"""
            try:
                p = pyaudio.PyAudio()

                # 创建音频流
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.output_rate,
                    output=True,
                    frames_per_buffer=4096
                )

                self.output_debug(f"🔊 音频播放线程已启动 (rate={self.output_rate}Hz)")

                while not self._stop_audio_event.is_set():
                    try:
                        # 从队列获取音频数据（超时0.1秒）
                        audio_data = self.__audio_queue.get(timeout=0.1)

                        if audio_data is None:  # 结束信号
                            break

                        # 播放音频
                        stream.write(audio_data)

                    except queue.Empty:
                        continue
                    except Exception as e:
                        self.output_error(f"音频播放错误: {e}")

                # 清理
                stream.stop_stream()
                stream.close()
                p.terminate()
                self.output_debug("🔇 音频播放线程已停止")

            except Exception as e:
                self.output_error(f"音频播放线程初始化失败: {e}")

        # 启动音频播放线程
        self._audio_thread = Thread(target=audio_player_loop, daemon=True)
        self._audio_thread.start()
        self.output_status(f"✅ 音频播放器已启动 (回调数量: {len(self._audio_callbacks)}, rate: {self.output_rate}Hz)")

    def stop_audio_player(self):
        """
        停止音频播放线程

        发送停止信号并等待音频播放线程结束。
        """
        if self._audio_thread is None or not self._audio_thread.is_alive():
            return

        # 发送停止信号
        self._stop_audio_event.set()

        # 发送结束标记到队列
        if self.__audio_queue:
            self.__audio_queue.put(None)

        # 等待线程结束（最多2秒）
        self._audio_thread.join(timeout=2.0)

        if self._audio_thread.is_alive():
            self.output_warning("音频播放线程未能在2秒内停止")

        self._audio_thread = None
        self.__audio_queue = None
        self._stop_audio_event = None

    def queue_audio(self, audio_data: bytes):
        """
        将音频数据放入播放队列，并触发所有注册的回调

        Args:
            audio_data: 音频数据（PCM格式）
        """
        # 1. 放入内部队列供播放
        if self.__audio_queue:
            self.__audio_queue.put(audio_data)

        # 2. 触发所有回调（用于转发到外部，如虚拟麦克风）
        for callback in self._audio_callbacks:
            try:
                callback(audio_data)
            except Exception as e:
                self.output_error(f"音频回调执行失败: {e}")

    def register_audio_callback(self, callback):
        """
        注册音频数据回调函数

        当收到音频数据时，除了播放外，还会调用所有注册的回调函数。
        这用于将音频数据转发到外部（例如虚拟麦克风）。

        Args:
            callback: 回调函数，签名应为 callback(audio_data: bytes)

        Example:
            client.register_audio_callback(lambda data: print(f"收到 {len(data)} 字节音频"))
        """
        if callback not in self._audio_callbacks:
            self._audio_callbacks.append(callback)
            self.output_status(f"已注册音频回调，当前回调数量: {len(self._audio_callbacks)}")

    def unregister_audio_callback(self, callback):
        """
        取消注册音频回调函数

        Args:
            callback: 要移除的回调函数
        """
        if callback in self._audio_callbacks:
            self._audio_callbacks.remove(callback)
            self.output_debug(f"已移除音频回调，当前回调数量: {len(self._audio_callbacks)}")

    def supports_voice_testing(self) -> bool:
        """
        检查是否支持音色试听功能

        默认实现返回 True（如果混入了这个类，通常支持试听）
        子类可以覆盖以添加额外条件检查。

        Returns:
            bool: True 如果支持试听功能
        """
        return True

    async def test_voice_async(self, text: str = "Hello, this is a test."):
        """
        试听音色（异步）

        生成一段测试音频并播放，让用户测试当前选择的音色效果。
        子类需要覆盖此方法来实现具体的试听逻辑。

        Args:
            text: 要朗读的测试文本

        Raises:
            NotImplementedError: 如果子类未实现试听功能
        """
        # 默认实现：子类应该覆盖
        raise NotImplementedError(
            f"{self.__class__.__name__} 应该实现 test_voice_async() 方法"
        )

    # 注意：get_supported_voices() 仍然是 abstractmethod，
    # 应该在具体 client 类中实现，而不是在 mixin 中
