"""
音频捕获线程
从指定设备捕获音频并发送到翻译服务
"""

import threading
try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    # 如果没有安装 PyAudioWPatch，使用标准 PyAudio
    import pyaudio
import asyncio
import logging
import audioop
import numpy as np
from typing import Callable, Optional

from output_manager import Out


class AudioCaptureThread:
    """音频捕获线程"""

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
        # 如果 chunk_size 是默认值 1600（适用于 16kHz），则重新计算
        if chunk_size == 1600 and sample_rate != 16000:
            self.chunk_size = int(sample_rate * 0.1)  # 100ms
            Out.debug(f"调整 chunk_size 为 {self.chunk_size} (100ms @ {sample_rate}Hz)")
        else:
            self.chunk_size = chunk_size

        # 目标格式（用于重采样和混音）
        self.target_sample_rate = target_sample_rate or sample_rate
        self.target_channels = target_channels or channels

        # 是否需要转换
        self.need_resample = (self.target_sample_rate != self.sample_rate)
        self.need_remix = (self.target_channels != self.channels)

        if self.need_resample or self.need_remix:
            Out.status(f"音频转换: {self.sample_rate}Hz {self.channels}ch -> {self.target_sample_rate}Hz {self.target_channels}ch")

        self.is_running = False
        self.thread = None
        self.pyaudio_instance = None
        self.stream = None

    def start(self):
        """启动捕获线程"""
        if self.is_running:
            Out.warning("音频捕获线程已在运行")
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

        Out.status(f"音频捕获线程已启动 (设备: {self.device_index}, 采样率: {self.sample_rate} Hz)")

    def stop(self):
        """停止捕获线程"""
        if not self.is_running:
            return

        Out.status("停止音频捕获线程...")
        self.is_running = False

        # 等待线程结束
        if self.thread:
            self.thread.join(timeout=2)

        # 清理资源
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
                Out.debug("音频流已关闭")
            except Exception as e:
                Out.debug(f"关闭音频流时出错: {e}")

        # 注意：不调用 terminate()，因为多个线程可能共享 PyAudio
        # 让 Python GC 自动清理 PyAudio 实例
        if self.pyaudio_instance:
            Out.debug("PyAudio 实例将由 GC 清理（不调用 terminate）")
            self.pyaudio_instance = None

        Out.status("音频捕获线程已停止")

    def _convert_audio(self, audio_data: bytes) -> bytes:
        """
        转换音频格式（重采样 + 混音）

        Args:
            audio_data: 原始音频数据（PCM 16-bit）

        Returns:
            bytes: 转换后的音频数据
        """
        # 1. 混音：立体声转单声道
        if self.need_remix and self.channels == 2 and self.target_channels == 1:
            # 使用 audioop 将立体声转为单声道
            audio_data = audioop.tomono(audio_data, 2, 0.5, 0.5)

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

    def _capture_loop(self):
        """音频捕获循环（在独立线程中运行）"""
        try:
            # 创建 PyAudio 实例
            self.pyaudio_instance = pyaudio.PyAudio()

            # 打开音频流
            self.stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=None  # 使用阻塞模式
            )

            Out.status("音频流已打开，开始捕获...")

            # 持续读取音频数据
            while self.is_running:
                try:
                    # 读取音频数据
                    audio_data = self.stream.read(
                        self.chunk_size,
                        exception_on_overflow=False
                    )

                    # 转换音频格式（如果需要）
                    if self.need_resample or self.need_remix:
                        audio_data = self._convert_audio(audio_data)

                    # 调用回调函数
                    if self.on_audio_chunk:
                        self.on_audio_chunk(audio_data)

                except IOError as e:
                    Out.debug(f"音频流读取错误: {e}")
                    continue

        except Exception as e:
            Out.error(f"音频捕获线程错误: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # 确保清理资源
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass

            if self.pyaudio_instance:
                try:
                    self.pyaudio_instance.terminate()
                except:
                    pass


# 测试代码
if __name__ == "__main__":
    import time

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # 回调函数：打印音频数据大小
    def on_audio(data: bytes):
        print(f"收到音频数据: {len(data)} 字节")

    # 创建音频捕获线程（使用默认设备）
    capture = AudioCaptureThread(
        device_index=None,  # 使用默认设备
        on_audio_chunk=on_audio
    )

    try:
        # 启动捕获
        capture.start()

        # 运行10秒
        print("音频捕获中...按 Ctrl+C 停止")
        time.sleep(10)

    except KeyboardInterrupt:
        print("\n用户中断")

    finally:
        # 停止捕获
        capture.stop()
