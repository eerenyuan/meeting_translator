"""
翻译服务适配器
封装 Qwen3 LiveTranslate 用于会议翻译
"""

import asyncio
import sys
import os
import logging
from typing import Callable, Optional

from translation_client_factory import TranslationClientFactory

logger = logging.getLogger(__name__)


# 设置全局unraisable异常处理器（抑制WebSocket关闭时的"Exception ignored"警告）
def _suppress_websocket_unraisable_exceptions(unraisable):
    """抑制WebSocket关闭时产生的不可触发异常"""
    # 检查是否是WebSocket close_connection相关的异常
    if unraisable.object and hasattr(unraisable.object, '__name__'):
        if 'close_connection' in unraisable.object.__name__:
            return  # 抑制

    # 检查异常类型
    if unraisable.exc_type and issubclass(unraisable.exc_type, RuntimeError):
        exc_msg = str(unraisable.exc_value) if unraisable.exc_value else ''
        if 'event loop' in exc_msg.lower():
            return  # 抑制 "no running event loop" 错误

    # 其他异常使用默认处理器
    sys.__unraisablehook__(unraisable)


# 安装全局unraisable异常处理器
sys.unraisablehook = _suppress_websocket_unraisable_exceptions


class MeetingTranslationService:
    """会议翻译服务（英文 → 中文）"""

    def __init__(
        self,
        api_key: str,
        on_translation: Callable[[str, str, bool], None],
        source_language: str = "en",
        target_language: str = "zh",
        audio_enabled: bool = False,
        voice: Optional[str] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        provider: Optional[str] = None
    ):
        """
        初始化翻译服务

        Args:
            api_key: API Key（或通过环境变量自动获取）
            on_translation: 翻译回调 (source_text, target_text, is_final)
            source_language: 源语言（默认英文）
            target_language: 目标语言（默认中文）
            audio_enabled: 是否启用音频输出（说模式需要）
            voice: 语音选择（provider-specific，或自动使用默认值）
            on_audio_chunk: 音频数据回调
            provider: 翻译服务提供商（aliyun/openai，默认从环境变量读取）
        """
        self.api_key = api_key
        self.on_translation = on_translation
        self.source_language = source_language
        self.target_language = target_language
        self.audio_enabled = audio_enabled
        self.voice = voice
        self.on_audio_chunk = on_audio_chunk
        self.provider = provider

        self.client = None
        self.is_running = False
        self.message_task = None
        self._audio_forward_thread = None

    async def start(self):
        """启动翻译服务"""
        if self.is_running:
            logger.warning("翻译服务已在运行")
            return

        logger.info("启动翻译服务...")

        try:
            # ！重要：先设置 is_running，避免竞态条件
            self.is_running = True

            # 使用工厂模式创建客户端（支持多个提供商）
            logger.info(f"创建翻译客户端（provider={self.provider or 'auto'}, audio_enabled={self.audio_enabled}）")
            self.client = TranslationClientFactory.create_client(
                provider=self.provider,
                api_key=self.api_key,
                source_language=self.source_language,
                target_language=self.target_language,
                voice=self.voice,
                audio_enabled=self.audio_enabled,
                glossary_file=None
            )

            # 连接到服务
            await self.client.connect()

            # 如果启用音频，启动音频转发线程
            if self.audio_enabled and self.on_audio_chunk:
                self._start_audio_forwarding()

            # 启动消息处理任务（带自动重连）
            self.message_task = asyncio.create_task(
                self._run_with_auto_reconnect()
            )

            logger.info("翻译服务已启动")

        except Exception as e:
            logger.error(f"启动翻译服务失败: {e}")
            raise

    async def stop(self):
        """停止翻译服务"""
        if not self.is_running:
            return

        logger.info("停止翻译服务...")

        self.is_running = False

        # 清空客户端的音频播放队列，避免停止时播放积压内容
        if self.client and hasattr(self.client, 'audio_playback_queue'):
            cleared = 0
            queue_size = self.client.audio_playback_queue.qsize()
            while not self.client.audio_playback_queue.empty():
                try:
                    self.client.audio_playback_queue.get_nowait()
                    cleared += 1
                except:
                    break
            if cleared > 0:
                logger.info(f"已清空客户端音频队列中的 {cleared}/{queue_size} 个音频块（停止前积压）")

        # 取消消息处理任务
        if self.message_task:
            self.message_task.cancel()
            try:
                await asyncio.wait_for(self.message_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                logger.debug("消息处理任务已取消")
            except Exception as e:
                logger.debug(f"取消消息任务时出错: {e}")

        # 关闭客户端
        if self.client:
            try:
                await asyncio.wait_for(self.client.close(), timeout=2.0)
                logger.debug("WebSocket 客户端已关闭")
            except asyncio.TimeoutError:
                logger.warning("关闭 WebSocket 超时")
            except Exception as e:
                logger.debug(f"关闭客户端时出错: {e}")

        logger.info("翻译服务已停止")

    async def send_audio_chunk(self, audio_data: bytes):
        """
        发送音频数据块

        Args:
            audio_data: PCM 音频数据（16000 Hz, 单声道, 16-bit）
        """
        if not self.is_running or not self.client:
            return

        await self.client.send_audio_chunk(audio_data)

    async def _run_with_auto_reconnect(self):
        """
        运行消息处理循环，带自动重连功能
        当检测到连接断开时，会自动尝试重连
        """
        reconnect_delay = 1  # 重连延迟（秒）- 减少到1秒加快重连
        max_reconnect_attempts = 5  # 最大重连次数 - 增加到5次（session timeout是常见情况）
        reconnect_count = 0

        while self.is_running:
            try:
                # 运行消息处理
                await self.client.handle_server_messages(self._on_text_received)

                # 如果正常退出循环，检查是否需要重连
                if self.is_running and not self.client.is_connected:
                    logger.warning("连接已断开，准备重连...")
                    reconnect_count += 1

                    if reconnect_count > max_reconnect_attempts:
                        logger.error(f"重连失败次数过多 ({max_reconnect_attempts})，停止服务")
                        # 通知用户
                        if self.on_translation:
                            self.on_translation(
                                "",
                                f"[错误] 连接断开，已尝试重连 {max_reconnect_attempts} 次失败",
                                is_final=True
                            )
                        break

                    # 等待后重连
                    logger.info(f"等待 {reconnect_delay} 秒后重连（第 {reconnect_count}/{max_reconnect_attempts} 次）...")
                    await asyncio.sleep(reconnect_delay)

                    # 关闭旧连接
                    try:
                        await self.client.close()
                    except:
                        pass

                    # 重新创建客户端（使用工厂模式）
                    self.client = TranslationClientFactory.create_client(
                        provider=self.provider,
                        api_key=self.api_key,
                        source_language=self.source_language,
                        target_language=self.target_language,
                        voice=self.voice,
                        audio_enabled=self.audio_enabled,
                        glossary_file=None
                    )

                    # 重新连接
                    await self.client.connect()
                    logger.info("重连成功（自动）")

                    # 重置重连计数
                    reconnect_count = 0

                    # 如果启用音频，重启音频转发
                    if self.audio_enabled and self.on_audio_chunk:
                        # 停止旧的转发线程
                        if hasattr(self, '_audio_forward_thread') and self._audio_forward_thread:
                            self._audio_forward_thread.join(timeout=1)
                        # 启动新的转发线程
                        self._start_audio_forwarding()

                    # 不显示"连接已恢复"消息（对于timeout这种正常情况，用户不需要知道）
                    # session timeout是Doubao API的正常行为，当没有音频输入时会超时

                else:
                    # 正常退出
                    break

            except asyncio.CancelledError:
                logger.debug("消息处理任务被取消")
                break
            except Exception as e:
                logger.error(f"消息处理错误: {e}")
                import traceback
                traceback.print_exc()

                # 等待后重试
                if self.is_running:
                    await asyncio.sleep(reconnect_delay)

    def _on_text_received(self, text: str):
        """
        文本接收回调（内部使用）

        Args:
            text: 接收到的文本（格式: "[源] xxx" 或 "[译] xxx" 或 "[译增量] xxx"）
        """
        # 解析文本
        if text.startswith("[源]"):
            source_text = text[4:].strip()
            # 暂存源文本（等待翻译）
            self._current_source = source_text

        elif text.startswith("[译增量]"):
            # 增量文本（未finalize）
            # 注意：每个 response.text.text 事件包含当前句子的完整状态（text + stash）
            # 不是增量追加，而是完整替换
            partial_text = text[6:].strip()

            # 直接替换（不累积）
            self._partial_translation = partial_text

            # 获取源文本
            source_text = getattr(self, '_current_source', '')

            # 调用用户回调（标记为增量）
            if self.on_translation:
                try:
                    self.on_translation(source_text, self._partial_translation, is_final=False)
                except Exception as e:
                    logger.error(f"翻译回调执行失败: {e}")

        elif text.startswith("[译]"):
            # 最终翻译文本
            target_text = text[4:].strip()

            # 清空累积的增量文本
            self._partial_translation = ""

            # 获取源文本
            source_text = getattr(self, '_current_source', '')

            # 调用用户回调（标记为最终）
            if self.on_translation:
                try:
                    self.on_translation(source_text, target_text, is_final=True)
                except Exception as e:
                    logger.error(f"翻译回调执行失败: {e}")

    def _start_audio_forwarding(self):
        """启动音频转发线程（从 API 队列→外部回调）"""
        import threading
        import queue

        audio_chunk_count = [0]  # 使用列表以便在闭包中修改

        def forward_loop():
            """音频转发循环（在独立线程中运行）"""
            logger.info("[音频转发] 转发循环已启动")

            while self.is_running:
                try:
                    # 从 API 客户端的队列获取音频数据
                    audio_data = self.client.audio_playback_queue.get(timeout=0.1)

                    if audio_data is None:
                        logger.info("[音频转发] 收到终止信号")
                        break

                    # 转发到外部回调（写入虚拟麦克风）
                    if self.on_audio_chunk:
                        audio_chunk_count[0] += 1
                        if audio_chunk_count[0] <= 3:  # 只记录前3个块
                            logger.info(f"[音频转发] 转发音频块 #{audio_chunk_count[0]}, 大小: {len(audio_data)} 字节")
                        self.on_audio_chunk(audio_data)

                    # 标记任务完成
                    self.client.audio_playback_queue.task_done()

                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"[音频转发] 转发错误: {e}")
                    import traceback
                    traceback.print_exc()

            logger.info(f"[音频转发] 转发循环已停止，共转发 {audio_chunk_count[0]} 个音频块")

        self._audio_forward_thread = threading.Thread(target=forward_loop, daemon=True)
        self._audio_forward_thread.start()
        logger.info("音频转发线程已启动")


class MeetingTranslationServiceWrapper:
    """
    翻译服务包装器（同步接口）
    在独立线程中运行异步事件循环
    """

    def __init__(
        self,
        api_key: str,
        on_translation: Callable[[str, str, bool], None],
        source_language: str = "en",
        target_language: str = "zh",
        audio_enabled: bool = False,
        voice: Optional[str] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        provider: Optional[str] = None,
        on_error: Optional[Callable[[str, Exception], None]] = None
    ):
        self.api_key = api_key
        self.on_translation = on_translation
        self.source_language = source_language
        self.target_language = target_language
        self.audio_enabled = audio_enabled
        self.voice = voice
        self.on_audio_chunk = on_audio_chunk
        self.provider = provider
        self.on_error = on_error

        self.service = None
        self.loop = None
        self.thread = None
        self.is_running = False
        self.startup_error = None

    def start(self):
        """启动翻译服务（同步方法）"""
        if self.is_running:
            return

        import threading

        # 创建事件循环
        self.loop = asyncio.new_event_loop()

        # 设置自定义异常处理器，抑制WebSocket关闭时的警告
        def exception_handler(loop, context):
            """自定义异常处理器，抑制WebSocket关闭相关的异常"""
            exception = context.get('exception')
            message = context.get('message', '')

            # 抑制WebSocket关闭相关的异常
            if exception and isinstance(exception, RuntimeError):
                if 'event loop' in str(exception).lower():
                    return  # 抑制 "no running event loop" 错误

            # 抑制 "Task was destroyed but it is pending" 警告
            if 'Task was destroyed but it is pending' in message:
                return

            # 抑制WebSocket close_connection相关的异常
            if 'close_connection' in message.lower():
                return

            # 其他异常正常处理
            loop.default_exception_handler(context)

        self.loop.set_exception_handler(exception_handler)

        # 在独立线程中运行事件循环
        def run_loop():
            asyncio.set_event_loop(self.loop)

            try:
                # 创建翻译服务
                self.service = MeetingTranslationService(
                    api_key=self.api_key,
                    on_translation=self.on_translation,
                    source_language=self.source_language,
                    target_language=self.target_language,
                    audio_enabled=self.audio_enabled,
                    voice=self.voice,
                    on_audio_chunk=self.on_audio_chunk,
                    provider=self.provider
                )

                # 启动翻译服务
                self.loop.run_until_complete(self.service.start())

                # 运行事件循环
                self.loop.run_forever()

            except Exception as e:
                logger.error(f"翻译服务启动失败: {e}")
                self.startup_error = e
                self.is_running = False

                # 调用错误回调（如果提供）
                if self.on_error:
                    error_message = self._format_error_message(e)
                    self.on_error(error_message, e)

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

        self.is_running = True
        logger.info("翻译服务包装器已启动")

    def stop(self):
        """停止翻译服务（同步方法）"""
        if not self.is_running:
            logger.debug("翻译服务已经停止，跳过")
            return

        try:
            logger.info("[STOP-1] 正在停止翻译服务...")
            self.is_running = False

            # 1. 停止翻译服务并等待完成
            if self.service and self.loop:
                try:
                    logger.debug("[STOP-2] 调用service.stop()...")
                    future = asyncio.run_coroutine_threadsafe(self.service.stop(), self.loop)
                    future.result(timeout=2)  # 减少超时时间到2秒
                    logger.debug("[STOP-3] 翻译服务已停止")
                except asyncio.TimeoutError:
                    logger.warning("[STOP-ERROR] 停止翻译服务超时（2秒），强制继续")
                except Exception as e:
                    logger.warning(f"[STOP-ERROR] 停止翻译服务时出错: {e}", exc_info=True)

            # 2. 给剩余任务时间自然完成（特别是WebSocket关闭）
            if self.loop and self.loop.is_running():
                try:
                    logger.debug("[STOP-4] 等待剩余任务完成...")
                    import time
                    time.sleep(0.2)  # 减少等待时间到200ms

                    # 获取所有待处理的任务
                    pending = asyncio.all_tasks(self.loop)
                    if pending:
                        logger.debug(f"[STOP-5] 仍有 {len(pending)} 个待处理任务，正在取消...")
                        for task in pending:
                            task.cancel()
                        # 给任务取消一点时间
                        time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"[STOP-ERROR] 处理剩余任务时出错: {e}", exc_info=True)

            # 3. 停止事件循环
            if self.loop and self.loop.is_running():
                logger.debug("[STOP-6] 停止事件循环...")
                try:
                    self.loop.call_soon_threadsafe(self.loop.stop)
                except Exception as e:
                    logger.warning(f"[STOP-ERROR] 停止事件循环时出错: {e}", exc_info=True)

            # 4. 等待线程结束
            if self.thread and self.thread.is_alive():
                logger.debug("[STOP-7] 等待服务线程结束...")
                self.thread.join(timeout=2)  # 减少到2秒
                if self.thread.is_alive():
                    logger.warning("[STOP-ERROR] 翻译服务线程未能在 2 秒内结束")

            # 5. 清理事件循环（注意：不在这里close，让GC处理）
            if self.loop:
                logger.debug("[STOP-8] 清理事件循环引用...")
                self.loop = None

            # 6. 清理服务对象
            self.service = None
            self.thread = None

            logger.info("[STOP-9] 翻译服务包装器已停止")

        except Exception as e:
            logger.critical(f"[STOP-CRITICAL] stop()方法发生严重错误: {e}", exc_info=True)
            # 确保清理状态
            self.is_running = False
            self.loop = None
            self.service = None
            self.thread = None

    def _format_error_message(self, error: Exception) -> str:
        """
        格式化错误消息，提供用户友好的提示

        Args:
            error: 异常对象

        Returns:
            用户友好的错误消息
        """
        error_str = str(error)
        provider_name = self.provider or "aliyun"

        # 检查是否是认证错误（HTTP 401）
        if "401" in error_str or "unauthorized" in error_str.lower():
            # 根据提供商给出具体的API Key环境变量名
            if provider_name == "openai":
                key_name = "OPENAI_API_KEY"
                key_url = "https://platform.openai.com/api-keys"
            elif provider_name == "aliyun" or provider_name == "alibaba":
                key_name = "DASHSCOPE_API_KEY 或 ALIYUN_API_KEY"
                key_url = "https://dashscope.console.aliyun.com/"
            else:
                key_name = f"{provider_name.upper()}_API_KEY"
                key_url = ""

            message = f"认证失败 (HTTP 401)：API Key 无效或未设置\n\n"
            message += f"提供商: {provider_name}\n"
            message += f"请检查 .env 文件中的 {key_name} 是否正确设置\n\n"
            if key_url:
                message += f"获取 API Key: {key_url}"

            return message

        # 检查是否是连接错误
        elif "connection" in error_str.lower() or "timeout" in error_str.lower():
            return f"连接失败：无法连接到 {provider_name} 服务\n\n请检查网络连接"

        # 其他错误
        else:
            return f"服务启动失败\n\n提供商: {provider_name}\n错误: {error_str}"

    def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块（同步方法）"""
        if not self.is_running or not self.service or not self.loop:
            return

        # Debug: Track audio sending (first 5 chunks)
        if not hasattr(self, '_send_count'):
            self._send_count = 0
        self._send_count += 1
        if self._send_count <= 5:
            logger.info(f"[AUDIO-SEND] Sending audio chunk #{self._send_count}, size={len(audio_data)} bytes, is_running={self.is_running}, loop_running={self.loop.is_running() if self.loop else 'N/A'}")

        # 在事件循环中执行（添加回调处理错误）
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.service.send_audio_chunk(audio_data),
                self.loop
            )
            # 添加错误处理回调（不等待结果，避免阻塞）
            def handle_error(fut):
                try:
                    fut.exception()
                except Exception as e:
                    if self._send_count <= 5:  # 只记录前5个错误
                        logger.error(f"[AUDIO-SEND] Error sending chunk #{self._send_count}: {e}")

            future.add_done_callback(handle_error)
        except Exception as e:
            if self._send_count <= 5:
                logger.error(f"[AUDIO-SEND] Failed to schedule audio send #{self._send_count}: {e}")


# 测试代码
if __name__ == "__main__":
    import time
    from dotenv import load_dotenv

    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # 获取 API Key
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
    if not api_key:
        print("❌ 请设置 DASHSCOPE_API_KEY 或 ALIYUN_API_KEY 环境变量")
        exit(1)

    # 翻译回调
    def on_translation(source, target):
        print(f"\n[源] {source}")
        print(f"[译] {target}")

    # 创建翻译服务
    service = MeetingTranslationServiceWrapper(
        api_key=api_key,
        on_translation=on_translation
    )

    try:
        # 启动服务
        service.start()
        time.sleep(2)  # 等待连接

        print("翻译服务已启动，等待音频输入...")
        print("（此测试代码不包含音频输入，请使用完整应用测试）")

        # 保持运行
        time.sleep(10)

    except KeyboardInterrupt:
        print("\n用户中断")

    finally:
        # 停止服务
        service.stop()
