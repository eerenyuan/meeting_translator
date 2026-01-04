"""
音频捕获线程（使用 PortAudio 回调模式）
从指定设备捕获音频并发送到翻译服务

回调模式优势：
- 非阻塞，PortAudio 底层驱动管理
- 优雅退出，只需停止流即可
- 避免线程竞争和阻塞问题
- 生产环境推荐方案
"""

import threading
import queue
try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    # 如果没有安装 PyAudioWPatch，使用标准 PyAudio
    import pyaudio
import logging
import audioop
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AudioCaptureThread:
    """音频捕获线程（使用回调模式）"""

    def __init__(
        self,
        device_index: int,
        on_audio_chunk: Callable[[bytes], None],
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1600,  # 100ms @ 16kHz
        target_sample_rate: Optional[int] = None,
        target_channels: Optional[int] = None
    ):
        """
        初始化音频捕获线程

        Args:
            device_index: PyAudio 设备索引
            on_audio_chunk: 音频数据回调函数
            sample_rate: 设备采样率（原生采样率）
            channels: 设备声道数（原生声道数）
            chunk_size: 每次读取的帧数
            target_sample_rate: 目标采样率（用于重采样），默认与 sample_rate 相同
            target_channels: 目标声道数（用于混音），默认与 channels 相同
        """
        self.device_index = device_index
        self.on_audio_chunk = on_audio_chunk
        self.sample_rate = sample_rate
        self.channels = channels

        # 根据采样率调整 chunk_size（保持 100ms 的缓冲时间）
        if chunk_size == 1600 and sample_rate != 16000:
            self.chunk_size = int(sample_rate * 0.1)  # 100ms
            logger.debug(f"调整 chunk_size 为 {self.chunk_size} (100ms @ {sample_rate}Hz)")
        else:
            self.chunk_size = chunk_size

        # 目标格式（用于重采样和混音）
        self.target_sample_rate = target_sample_rate or sample_rate
        self.target_channels = target_channels or channels

        # 是否需要转换
        self.need_resample = (self.target_sample_rate != self.sample_rate)
        self.need_remix = (self.target_channels != self.channels)

        if self.need_resample or self.need_remix:
            logger.info(f"音频转换: {self.sample_rate}Hz {self.channels}ch -> {self.target_sample_rate}Hz {self.target_channels}ch")

        self.is_running = False
        self.pyaudio_instance = None
        self.stream = None

        # 音频队列（用于回调线程到主线程的数据传递）
        self.audio_queue = queue.Queue(maxsize=10)

        # 处理线程（从队列取出音频数据并调用回调）
        self.process_thread = None

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """
        PortAudio 回调函数（在 PortAudio 内部线程中调用）

        这个函数是非阻塞的，必须快速返回
        """
        if status:
            logger.debug(f"音频回调状态: {status}")

        if not self.is_running:
            # 停止回调，返回 paComplete
            return (None, pyaudio.paComplete)

        # 将音频数据放入队列（非阻塞）
        try:
            self.audio_queue.put_nowait(in_data)
        except queue.Full:
            # 队列满了，丢弃这一帧（避免阻塞）
            pass

        # 继续回调
        return (None, pyaudio.paContinue)

    def _process_loop(self):
        """
        音频处理循环（在独立线程中运行）
        从队列取出音频数据，进行转换，然后调用回调
        """
        while self.is_running:
            try:
                # 从队列获取音频数据（带超时）
                audio_data = self.audio_queue.get(timeout=0.1)

                if audio_data is None:
                    break

                # 转换音频格式（重采样 + 混音）
                if self.need_resample or self.need_remix:
                    audio_data = self._convert_audio(audio_data)

                # 调用外部回调
                self.on_audio_chunk(audio_data)

            except queue.Empty:
                # 超时，继续
                continue
            except Exception as e:
                logger.error(f"音频处理出错: {e}")
                continue

        logger.debug("音频处理循环已退出")

    def start(self):
        """启动捕获（使用回调模式）"""
        if self.is_running:
            logger.warning("音频捕获线程已在运行")
            return

        self.is_running = True

        # 创建 PyAudio 实例
        self.pyaudio_instance = pyaudio.PyAudio()

        # 打开音频流（使用回调模式）
        self.stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size,
            stream_callback=self._audio_callback,  # 使用回调模式
            start=False  # 不自动启动，等待显式启动
        )

        # 启动音频处理线程
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()

        # 启动流
        self.stream.start_stream()

        logger.info(f"音频捕获已启动（回调模式，设备: {self.device_index}, 采样率: {self.sample_rate} Hz)")

    def stop(self):
        """停止捕获（回调模式安全退出）"""
        if not self.is_running:
            return

        logger.info("停止音频捕获...")

        # 设置停止标志
        self.is_running = False

        # 停止流（PortAudio 会停止调用回调）
        if self.stream is not None:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                    logger.debug("音频流已停止")
            except Exception as e:
                logger.warning(f"停止音频流时出错: {e}")

        # 等待处理线程退出
        if self.process_thread and self.process_thread.is_alive():
            logger.debug("等待音频处理线程退出...")
            self.process_thread.join(timeout=2)

        # 关闭流（现在安全了，因为回调已经停止）
        if self.stream is not None:
            try:
                self.stream.close()
                logger.debug("音频流已关闭")
            except Exception as e:
                logger.warning(f"关闭音频流时出错: {e}")

        # 终止 PyAudio
        if self.pyaudio_instance is not None:
            try:
                self.pyaudio_instance.terminate()
                logger.debug("PyAudio 实例已终止")
            except Exception as e:
                logger.warning(f"终止 PyAudio 时出错: {e}")

        # 清理引用
        self.stream = None
        self.pyaudio_instance = None
        self.process_thread = None

        # 清空队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        logger.info("音频捕获已停止")

    def _convert_audio(self, audio_data: bytes) -> bytes:
        """
        转换音频格式（重采样 + 混音）

        Args:
            audio_data: 原始音频数据（PCM 16-bit）

        Returns:
            bytes: 转换后的音频数据
        """
        # 1. 混音：立体声转单声道
        if self.need_remix and self.channels == 2:
            audio_data = audioop.tomono(audio_data, 2, 1, 1)  # 左右声道平均

        # 2. 重采样
        if self.need_resample:
            # 使用 audioop 进行重采样
            audio_data, _ = audioop.ratecv(
                audio_data,
                2,  # 样本宽度（16-bit = 2 bytes）
                self.target_channels,  # 声道数（已经混音过了）
                self.sample_rate,  # 源采样率
                self.target_sample_rate,  # 目标采样率
                None  # 状态（None 表示新的转换）
            )

        return audio_data
