# -*- coding: utf-8 -*-
"""
音频输出线程 - 写入虚拟麦克风（VoiceMeeter）
支持动态变速以缓解队列堆积
"""
import threading
import queue
import logging
import audioop
import tempfile
import wave
import numpy as np
import os

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio

try:
    from audiotsm import wsola
    from audiotsm.io.wav import WavReader, WavWriter
    WSOLA_AVAILABLE = True
except ImportError:
    WSOLA_AVAILABLE = False

from output_manager import Out


class AudioOutputThread:
    """音频输出线程（写入虚拟麦克风）"""

    def __init__(
        self,
        device_index: int,
        input_sample_rate: int = 24000,  # Qwen3 API 输出 24kHz
        output_sample_rate: int = 44100,  # VoiceMeeter 设备采样率
        channels: int = 1,
        chunk_size: int = 4410,  # 100ms @ 44.1kHz
        enable_dynamic_speed: bool = True,  # 启用动态变速
        max_speed: float = 2.0,  # 最大速度
        queue_threshold: int = 20,  # 队列阈值（低于此值正常播放）
        target_catchup_time: float = 10.0,  # 目标追赶时间（秒）
        max_chunks_per_batch: int = 50  # 单次 WSOLA 最大处理 chunk 数
    ):
        """
        初始化音频输出线程

        Args:
            device_index: PyAudio 输出设备索引（VoiceMeeter Input）
            input_sample_rate: 输入采样率（24kHz，匹配 API 输出）
            output_sample_rate: 输出采样率（设备采样率，通常 44100 Hz）
            channels: 声道数（单声道）
            chunk_size: 缓冲区大小（基于输出采样率）
            enable_dynamic_speed: 是否启用动态变速（根据队列深度）
            max_speed: 最大播放速度（2.0 = 两倍速）
            queue_threshold: 队列阈值，低于此值正常播放（推荐 20）
            target_catchup_time: 目标追赶时间（秒），用于计算自适应速度（推荐 10）
            max_chunks_per_batch: 单次 WSOLA 处理的最大 chunk 数（推荐 50）
        """
        self.device_index = device_index
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.channels = channels
        self.chunk_size = chunk_size

        # 动态变速参数（自适应方案）
        self.enable_dynamic_speed = enable_dynamic_speed and WSOLA_AVAILABLE
        self.max_speed = max_speed
        self.queue_threshold = queue_threshold
        self.target_catchup_time = target_catchup_time
        self.max_chunks_per_batch = max_chunks_per_batch

        if self.enable_dynamic_speed and not WSOLA_AVAILABLE:
            Out.warning("动态变速需要 audiotsm 库，已禁用。请运行: pip install audiotsm")
            self.enable_dynamic_speed = False

        self.is_running = False
        self.thread = None
        self.pyaudio_instance = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=200)  # 较大队列以处理长翻译

        # 统计信息
        self.queue_full_warnings = 0
        self.speed_changes = 0

    def start(self):
        """启动输出线程"""
        if self.is_running:
            Out.warning("音频输出线程已在运行")
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._output_loop, daemon=True)
        self.thread.start()

        if self.enable_dynamic_speed:
            Out.status(
                f"音频输出线程已启动（设备: {self.device_index}, "
                f"自适应变速: 最高{self.max_speed}x, "
                f"队列阈值: {self.queue_threshold}, "
                f"追赶时间: {self.target_catchup_time}s）"
            )
        else:
            Out.status(f"音频输出线程已启动（设备: {self.device_index}, 动态变速: 禁用）")

    def stop(self):
        """停止输出线程"""
        if not self.is_running:
            return

        Out.status("停止音频输出线程...")
        self.is_running = False

        # 发送终止信号
        try:
            self.audio_queue.put(None, timeout=0.5)
        except queue.Full:
            pass

        if self.thread:
            self.thread.join(timeout=2)

        # 清理资源
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                Out.debug(f"关闭输出流时出错: {e}")

        if self.pyaudio_instance:
            try:
                self.pyaudio_instance.terminate()
            except Exception as e:
                Out.debug(f"终止 PyAudio 时出错: {e}")

        Out.status("音频输出线程已停止")

    def _calculate_adaptive_speed(self, queue_size: int) -> float:
        """
        根据队列大小计算自适应播放速度

        公式: speed = min((queue_size + 10*x) / (10*x), max_speed)
        其中 x = target_catchup_time（目标追赶时间）

        物理意义：
        - 当前堆积: queue_size chunks
        - x秒正常播放: 10*x chunks
        - x秒预计新增: 10*x chunks
        - 需在x秒内消化: queue_size + 10*x chunks
        - 所需速度: (queue_size + 10*x) / (10*x)

        Args:
            queue_size: 当前队列中的 chunk 数量（每个约100ms）

        Returns:
            自适应速度（1.0 到 max_speed 之间）
        """
        if queue_size < self.queue_threshold:
            return 1.0  # 队列正常，不加速

        # 计算理论速度
        chunks_in_catchup_time = 10 * self.target_catchup_time
        target_speed = (queue_size + chunks_in_catchup_time) / chunks_in_catchup_time

        # 限制最大速度
        return min(target_speed, self.max_speed)

    def _apply_wsola_speed(self, audio_data: bytes, speed_factor: float) -> bytes:
        """
        使用 WSOLA 对音频应用速度变换

        Args:
            audio_data: PCM16 音频数据 (input_sample_rate)
            speed_factor: 速度倍数 (>1 = 加速)

        Returns:
            变速后的音频数据
        """
        if abs(speed_factor - 1.0) < 0.01:
            # 速度接近 1.0，无需处理
            return audio_data

        # 转换为 numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # 使用临时文件（audiotsm 需要文件 I/O）
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_in:
            temp_in_path = temp_in.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_out:
            temp_out_path = temp_out.name

        try:
            # 写入临时输入文件
            with wave.open(temp_in_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.input_sample_rate)
                wf.writeframes(audio_data)

            # 应用 WSOLA
            with WavReader(temp_in_path) as reader:
                with WavWriter(temp_out_path, reader.channels, reader.samplerate) as writer:
                    tsm = wsola(channels=reader.channels, speed=speed_factor)
                    tsm.run(reader, writer)

            # 读取输出
            with wave.open(temp_out_path, 'rb') as wf:
                output_bytes = wf.readframes(wf.getnframes())

            return output_bytes

        except Exception as e:
            Out.error(f"WSOLA 处理失败: {e}")
            return audio_data  # 失败时返回原始音频

        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_in_path):
                    os.unlink(temp_in_path)
                if os.path.exists(temp_out_path):
                    os.unlink(temp_out_path)
            except:
                pass

    def write_audio_chunk(self, audio_data: bytes):
        """
        写入音频数据块（直接入队原始数据，在播放线程中批量处理）

        Args:
            audio_data: PCM 音频数据（input_sample_rate=24kHz, 单声道, 16-bit）
        """
        if not self.is_running:
            return

        # 如果输出设备是立体声（channels=2），需要将单声道转换为立体声
        if self.channels == 2:
            # 单声道 → 立体声：复制到两个声道
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            stereo_array = np.zeros(len(audio_array) * 2, dtype=np.int16)
            stereo_array[0::2] = audio_array  # 左声道
            stereo_array[1::2] = audio_array  # 右声道
            audio_data = stereo_array.tobytes()

        # 注意：为了性能，直接入队原始 24kHz 数据
        # WSOLA 和重采样都在 _output_loop 中批量处理

        try:
            # 先尝试非阻塞写入
            self.audio_queue.put_nowait(audio_data)
        except queue.Full:
            # 队列满时，使用短超时的阻塞写入
            try:
                self.audio_queue.put(audio_data, timeout=2.0)

                # 记录队列满的情况
                self.queue_full_warnings += 1
                if self.queue_full_warnings % 50 == 1:
                    Out.warning(
                        f"音频输出队列已满 {self.queue_full_warnings} 次，使用阻塞写入保证完整性（可能略有延迟）"
                    )
            except queue.Full:
                # 如果 2 秒后仍然无法写入，说明播放严重滞后，记录错误
                Out.error("音频输出队列持续满载，无法写入音频块")

    def _resample_audio(self, audio_data: bytes, state=None) -> tuple:
        """
        重采样音频（24kHz -> output_sample_rate）

        Args:
            audio_data: 24kHz PCM16 数据
            state: 重采样状态（用于连续重采样）

        Returns:
            (resampled_data, new_state)
        """
        if self.input_sample_rate == self.output_sample_rate:
            return audio_data, state

        resampled_data, new_state = audioop.ratecv(
            audio_data,
            2,  # 16-bit = 2 bytes
            self.channels,
            self.input_sample_rate,
            self.output_sample_rate,
            state
        )
        return resampled_data, new_state

    def _output_loop(self):
        """音频输出循环（自适应批量处理）"""
        try:
            # 创建 PyAudio 实例
            self.pyaudio_instance = pyaudio.PyAudio()

            # 打开输出流
            self.stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.output_sample_rate,
                output=True,
                output_device_index=self.device_index,
                frames_per_buffer=self.chunk_size
            )

            Out.status(f"音频输出流已打开（{self.output_sample_rate}Hz, {self.channels}ch）")

            # 重采样状态（用于批量处理）
            resample_state = None

            # 持续写入音频数据
            while self.is_running:
                try:
                    # 获取当前队列大小
                    queue_size = self.audio_queue.qsize()

                    if queue_size < self.queue_threshold:
                        # 队列正常 - 逐个播放
                        audio_data = self.audio_queue.get(timeout=0.1)

                        # 检查终止信号
                        if audio_data is None:
                            break

                        # 重采样（如果需要）
                        audio_data, resample_state = self._resample_audio(audio_data, resample_state)

                        # 写入音频流（带错误检测）
                        try:
                            self.stream.write(audio_data)
                        except Exception as write_err:
                            Out.error(f"音频写入失败（设备可能已断开或状态变化）: {write_err}")
                            # 清空队列，避免阻塞翻译服务
                            while not self.audio_queue.empty():
                                try:
                                    self.audio_queue.get_nowait()
                                except:
                                    break
                            Out.error("音频输出已停止，请重新启动翻译")
                            self.is_running = False
                            break

                    else:
                        # 队列堆积 - 批量加速处理
                        # 计算自适应速度（基于总队列长度）
                        adaptive_speed = self._calculate_adaptive_speed(queue_size)

                        # 取出批量 chunks（不超过 max_chunks_per_batch）
                        chunks_to_take = min(queue_size, self.max_chunks_per_batch)
                        chunks = []
                        for _ in range(chunks_to_take):
                            chunk = self.audio_queue.get(timeout=0.1)
                            if chunk is None:  # 终止信号
                                self.is_running = False
                                break
                            chunks.append(chunk)

                        if not chunks:
                            continue

                        # 合并所有 chunks（24kHz 数据）
                        combined_audio = b''.join(chunks)

                        # 应用 WSOLA 加速（在 24kHz 时，更快）
                        if self.enable_dynamic_speed and adaptive_speed > 1.05:
                            accelerated_audio = self._apply_wsola_speed(combined_audio, adaptive_speed)

                            # 记录日志
                            self.speed_changes += 1
                            if self.speed_changes % 10 == 1:
                                Out.status(
                                    f"自适应加速: {adaptive_speed:.2f}x "
                                    f"(队列: {queue_size} → {self.audio_queue.qsize()}, "
                                    f"处理: {chunks_to_take} chunks)"
                                )
                        else:
                            accelerated_audio = combined_audio

                        # 重采样到输出采样率（批量处理）
                        output_audio, resample_state = self._resample_audio(accelerated_audio, resample_state)

                        # 写入音频流（带错误检测）
                        try:
                            self.stream.write(output_audio)
                        except Exception as write_err:
                            Out.error(f"音频写入失败（设备可能已断开或状态变化）: {write_err}")
                            # 清空队列，避免阻塞翻译服务
                            while not self.audio_queue.empty():
                                try:
                                    self.audio_queue.get_nowait()
                                except:
                                    break
                            Out.error("音频输出已停止，请重新启动翻译")
                            self.is_running = False
                            break

                except queue.Empty:
                    continue
                except Exception as e:
                    Out.error(f"写入音频数据时出错: {e}")
                    import traceback
                    traceback.print_exc()

        except Exception as e:
            Out.error(f"音频输出线程错误: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # 确保清理资源
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
