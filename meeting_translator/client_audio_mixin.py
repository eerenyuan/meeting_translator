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

    使用方法：
        class MyS2SClient(BaseTranslationClient, OutputMixin, AudioPlayerMixin):
            pass
    """

    def __init__(self, *args, **kwargs):
        """
        初始化音频播放相关属性

        注意：这个 mixin 期望在类的 __init__ 中被正确调用。
        使用 cooperative multiple inheritance:
            super().__init__(*args, **kwargs)
        """
        # 音频播放线程
        self._audio_thread: Optional[Thread] = None
        self._audio_queue: Optional[queue.Queue] = None
        self._stop_audio_event: Optional[asyncio.Event] = None

        # 调用下一个类的 __init__ (cooperative inheritance)
        super().__init__(*args, **kwargs)

    def start_audio_player(self):
        """
        启动音频播放线程

        创建后台线程来播放接收到的音频数据。
        线程会从 self._audio_queue 获取音频数据并播放。
        """
        if self._audio_thread is not None and self._audio_thread.is_alive():
            # 音频播放线程已在运行
            return

        import pyaudio
        import logger

        self._audio_queue = queue.Queue()
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

                logger.info(f"🔊 音频播放线程已启动 (rate={self.output_rate}Hz)")

                while not self._stop_audio_event.is_set():
                    try:
                        # 从队列获取音频数据（超时0.1秒）
                        audio_data = self._audio_queue.get(timeout=0.1)

                        if audio_data is None:  # 结束信号
                            break

                        # 播放音频
                        stream.write(audio_data)

                    except queue.Empty:
                        continue
                    except Exception as e:
                        logger.error(f"音频播放错误: {e}")

                # 清理
                stream.stop_stream()
                stream.close()
                p.terminate()
                logger.info("🔇 音频播放线程已停止")

            except Exception as e:
                logger.error(f"音频播放线程初始化失败: {e}")

        # 启动音频播放线程
        self._audio_thread = Thread(target=audio_player_loop, daemon=True)
        self._audio_thread.start()

    def stop_audio_player(self):
        """
        停止音频播放线程

        发送停止信号并等待音频播放线程结束。
        """
        if self._audio_thread is None or not self._audio_thread.is_alive():
            return

        import logger

        # 发送停止信号
        self._stop_audio_event.set()

        # 发送结束标记到队列
        if self._audio_queue:
            self._audio_queue.put(None)

        # 等待线程结束（最多2秒）
        self._audio_thread.join(timeout=2.0)

        if self._audio_thread.is_alive():
            logger.warning("音频播放线程未能在2秒内停止")

        self._audio_thread = None
        self._audio_queue = None
        self._stop_audio_event = None

    def queue_audio(self, audio_data: bytes):
        """
        将音频数据放入播放队列

        Args:
            audio_data: 音频数据（PCM格式）
        """
        if self._audio_queue:
            self._audio_queue.put(audio_data)

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
