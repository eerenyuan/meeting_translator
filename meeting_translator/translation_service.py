"""
翻译服务适配器
封装 Qwen3 LiveTranslate 用于会议翻译
"""

import asyncio
import sys
import os
from typing import Callable, Optional

# 添加 poc 目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'poc'))

from translation_client_factory import TranslationClientFactory

from output_manager import Out


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
            provider: 翻译服务提供商（aliyun/openai/doubao，默认从环境变量读取）
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
            Out.warning("翻译服务已在运行")
            return

        Out.status("启动翻译服务...")

        try:
            # ！重要：先设置 is_running，避免竞态条件
            self.is_running = True

            # 创建音频队列（用于 S2S 模式）
            import queue
            audio_queue = queue.Queue() if self.audio_enabled else None

            # 使用工厂模式创建客户端（支持多个提供商）
            Out.status(f"创建翻译客户端（provider={self.provider or 'auto'}, audio_enabled={self.audio_enabled}）")
            self.client = TranslationClientFactory.create_client(
                provider=self.provider,
                api_key=self.api_key,
                source_language=self.source_language,
                target_language=self.target_language,
                voice=self.voice,
                audio_enabled=self.audio_enabled,
                audio_queue=audio_queue,  # 传递内部队列
                glossary=None  # 不使用词汇表
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

            Out.status("翻译服务已启动")

        except Exception as e:
            Out.error(f"启动翻译服务失败: {e}")
            raise

    async def stop(self):
        """停止翻译服务"""
        if not self.is_running:
            return

        Out.status("停止翻译服务...")

        self.is_running = False

        # 取消消息处理任务
        if self.message_task:
            self.message_task.cancel()
            try:
                await asyncio.wait_for(self.message_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                Out.debug("消息处理任务已取消")
            except Exception as e:
                Out.debug(f"取消消息任务时出错: {e}")

        # 关闭客户端
        if self.client:
            try:
                await asyncio.wait_for(self.client.close(), timeout=2.0)
                Out.debug("WebSocket 客户端已关闭")
            except asyncio.TimeoutError:
                Out.warning("关闭 WebSocket 超时")
            except Exception as e:
                Out.debug(f"关闭客户端时出错: {e}")

        Out.status("翻译服务已停止")

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
        reconnect_delay = 2  # 重连延迟（秒）
        max_reconnect_attempts = 3  # 最大重连次数
        reconnect_count = 0

        while self.is_running:
            try:
                # 运行消息处理
                await self.client.handle_server_messages(self._on_text_received)

                # 如果正常退出循环，检查是否需要重连
                if self.is_running and not self.client.is_connected:
                    Out.warning("连接已断开，准备重连...")
                    reconnect_count += 1

                    if reconnect_count > max_reconnect_attempts:
                        Out.error(f"重连失败次数过多 ({max_reconnect_attempts})，停止服务")
                        # 通知用户
                        if self.on_translation:
                            self.on_translation(
                                "",
                                f"[错误] 连接断开，已尝试重连 {max_reconnect_attempts} 次失败",
                                is_final=True
                            )
                        break

                    # 等待后重连
                    Out.status(f"等待 {reconnect_delay} 秒后重连（第 {reconnect_count}/{max_reconnect_attempts} 次）...")
                    await asyncio.sleep(reconnect_delay)

                    # 关闭旧连接
                    try:
                        await self.client.close()
                    except:
                        pass

                    # 创建新的音频队列（用于 S2S 模式）
                    import queue
                    audio_queue = queue.Queue() if self.audio_enabled else None

                    # 重新创建客户端（使用工厂模式）
                    self.client = TranslationClientFactory.create_client(
                        provider=self.provider,
                        api_key=self.api_key,
                        source_language=self.source_language,
                        target_language=self.target_language,
                        voice=self.voice,
                        audio_enabled=self.audio_enabled,
                        audio_queue=audio_queue,
                        glossary=None
                    )

                    # 重新连接
                    await self.client.connect()
                    Out.status("重连成功")

                    # 重置重连计数
                    reconnect_count = 0

                    # 如果启用音频，重启音频转发
                    if self.audio_enabled and self.on_audio_chunk:
                        # 停止旧的转发线程
                        if hasattr(self, '_audio_forward_thread') and self._audio_forward_thread:
                            self._audio_forward_thread.join(timeout=1)
                        # 启动新的转发线程
                        self._start_audio_forwarding()

                    # 通知用户重连成功
                    if self.on_translation:
                        self.on_translation(
                            "",
                            "[提示] 连接已恢复",
                            is_final=True
                        )

                else:
                    # 正常退出
                    break

            except asyncio.CancelledError:
                Out.debug("消息处理任务被取消")
                break
            except Exception as e:
                Out.error(f"消息处理错误: {e}")
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
                    Out.error(f"翻译回调执行失败: {e}")

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
                    Out.error(f"翻译回调执行失败: {e}")

    def _start_audio_forwarding(self):
        """启动音频转发线程（从 API 队列→外部回调）"""
        import threading
        import queue

        audio_chunk_count = [0]  # 使用列表以便在闭包中修改

        def forward_loop():
            """音频转发循环（在独立线程中运行）"""
            Out.status("[音频转发] 转发循环已启动")

            while self.is_running:
                try:
                    # 从 API 客户端的外部队列获取音频数据
                    audio_data = self.client.audio_queue.get(timeout=0.1)

                    if audio_data is None:
                        Out.status("[音频转发] 收到终止信号")
                        break

                    # 转发到外部回调（写入虚拟麦克风）
                    if self.on_audio_chunk:
                        audio_chunk_count[0] += 1
                        if audio_chunk_count[0] <= 3:  # 只记录前3个块
                            Out.status(f"[音频转发] 转发音频块 #{audio_chunk_count[0]}, 大小: {len(audio_data)} 字节")
                        self.on_audio_chunk(audio_data)

                    # 标记任务完成
                    self.client.audio_queue.task_done()

                except queue.Empty:
                    continue
                except Exception as e:
                    Out.error(f"[音频转发] 转发错误: {e}")
                    import traceback
                    traceback.print_exc()

            Out.status(f"[音频转发] 转发循环已停止，共转发 {audio_chunk_count[0]} 个音频块")

        self._audio_forward_thread = threading.Thread(target=forward_loop, daemon=True)
        self._audio_forward_thread.start()
        Out.status("音频转发线程已启动")


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
        provider: Optional[str] = None
    ):
        self.api_key = api_key
        self.on_translation = on_translation
        self.source_language = source_language
        self.target_language = target_language
        self.audio_enabled = audio_enabled
        self.voice = voice
        self.on_audio_chunk = on_audio_chunk
        self.provider = provider

        self.service = None
        self.loop = None
        self.thread = None
        self.is_running = False

    def start(self):
        """启动翻译服务（同步方法）"""
        if self.is_running:
            return

        import threading

        # 创建事件循环
        self.loop = asyncio.new_event_loop()

        # 在独立线程中运行事件循环
        def run_loop():
            asyncio.set_event_loop(self.loop)

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

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

        self.is_running = True
        Out.status("翻译服务包装器已启动")

    def stop(self):
        """停止翻译服务（同步方法）"""
        if not self.is_running:
            return

        Out.status("正在停止翻译服务...")
        self.is_running = False

        # 1. 停止翻译服务并等待完成
        if self.service and self.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.service.stop(), self.loop)
                future.result(timeout=3)  # 等待 stop() 完成，最多等待 3 秒
                Out.debug("翻译服务已停止")
            except Exception as e:
                Out.warning(f"停止翻译服务时出错: {e}")

        # 2. 取消所有剩余任务
        if self.loop and self.loop.is_running():
            try:
                # 获取所有待处理的任务并取消
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                Out.debug(f"已取消 {len(pending)} 个待处理任务")
            except Exception as e:
                Out.debug(f"取消任务时出错: {e}")

        # 3. 停止事件循环
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        # 4. 等待线程结束
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                Out.warning("翻译服务线程未能在 3 秒内结束")

        # 5. 清理事件循环
        if self.loop:
            try:
                # 确保事件循环已停止
                if self.loop.is_running():
                    self.loop.stop()

                # 关闭事件循环
                if not self.loop.is_closed():
                    self.loop.close()
                    Out.debug("事件循环已关闭")
            except Exception as e:
                Out.debug(f"关闭事件循环时出错: {e}")
            finally:
                self.loop = None

        # 6. 清理服务对象
        self.service = None
        self.thread = None

        Out.status("翻译服务包装器已停止")

    def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据块（同步方法）"""
        if not self.is_running or not self.service or not self.loop:
            return

        # 在事件循环中执行
        asyncio.run_coroutine_threadsafe(
            self.service.send_audio_chunk(audio_data),
            self.loop
        )


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
