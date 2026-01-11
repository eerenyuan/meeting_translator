"""
会议翻译主应用
整合音频捕获、翻译服务和字幕显示
"""

import sys
import os
import logging
from datetime import datetime

# Fix Qt plugin path for Windows BEFORE importing PyQt5 widgets
if sys.platform == 'win32':
    import PyQt5
    pyqt5_dir = os.path.dirname(PyQt5.__file__)
    qt_plugin_path = os.path.join(pyqt5_dir, 'Qt5', 'plugins')
    os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(qt_plugin_path, 'platforms')

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from dotenv import load_dotenv


class VoicePreviewSignals(QObject):
    """音色试听信号"""
    finished = pyqtSignal()


from audio_device_manager import AudioDeviceManager
from audio_capture_thread import AudioCaptureThread
from audio_output_thread import AudioOutputThread
from translation_service import MeetingTranslationServiceWrapper
from translation_mode import TranslationMode, ModeConfig
from subtitle_window import SubtitleWindow
from config_manager import ConfigManager
from output_manager import Out, MessageType
from output_handlers import ConsoleHandler, LogFileHandler, AlertHandler, SubtitleHandler
from paths import LOGS_DIR, RECORDS_DIR, ensure_directories, get_initialization_message

# 配置日志（同时输出到控制台和文件）
import sys
ensure_directories()  # 确保所有目录存在

# 注意：此时 OutputManager 还未初始化，使用 print 显示启动信息

print(f"配置目录: {os.path.join(os.path.expanduser('~'), 'Documents', 'meeting_translator', 'config')}")
print(f"记录目录: {os.path.join(os.path.expanduser('~'), 'Documents', 'meeting_translator', 'records')}")

# 加载环境变量
load_dotenv()


class MeetingTranslatorApp(QWidget):
    """会议翻译主应用"""

    # Provider 输出采样率映射（S2S 模式）
    PROVIDER_OUTPUT_RATES = {
        "aliyun": 24000,   # Qwen: 24kHz
        "openai": 24000,   # OpenAI Realtime: 24kHz
        "doubao": 16000,   # Doubao: 16kHz
    }

    def __init__(self):
        super().__init__()

        # 获取 API Key
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
        if not self.api_key:
            Out.error("未设置 DASHSCOPE_API_KEY 或 ALIYUN_API_KEY 环境变量")
            sys.exit(1)

        # API 提供商
        self.provider = "aliyun"  # 默认阿里云

        # 翻译模式
        self.current_mode = TranslationMode.LISTEN

        # 初始化组件
        self.device_manager = AudioDeviceManager()
        self.config_manager = ConfigManager()

        # 听模式组件
        self.listen_audio_capture = None
        self.listen_translation_service = None

        # 说模式组件
        self.speak_audio_capture = None
        self.speak_translation_service = None
        self.speak_audio_output = None  # AudioOutputThread

        # 字幕窗口
        self.subtitle_window = None

        # 初始化 OutputManager
        self._init_output_manager()

        # 运行状态
        self.is_running = False
        self.is_loading_config = True  # 标志：正在加载配置，不要自动保存

        # 初始化 UI
        self.init_ui()

        # 加载样式表
        self.load_stylesheet()

        # 加载设备列表
        self.load_devices()

        # 加载上次保存的配置
        self.load_config()

        # 配置加载完成，允许自动保存
        self.is_loading_config = False

        # 检查并生成缺失的音色样本文件
        self._check_and_generate_voice_samples()

        # 检查并提示迁移旧文件（如果有）
        init_message = get_initialization_message()
        if init_message:
            # 显示迁移信息
            print("\n" + "="*60)
            print(init_message)
            print("="*60 + "\n")

    def _init_output_manager(self):
        log_file = os.path.join(LOGS_DIR, f"translator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(name)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8')  # 文件输出
            ]
        )

        """初始化 OutputManager 并添加 handlers"""
        manager = Out

        # 清空临时 handlers（移除 __init__ 中添加的临时 ConsoleHandler）
        manager.handlers.clear()

        # 1. 添加控制台处理器（只显示翻译结果和错误，隐藏状态信息）
        console_handler = ConsoleHandler(
            enabled_types=[
                MessageType.TRANSLATION,  # ✅ 显示最终翻译
                MessageType.SUBTITLE,     # ✅ 显示字幕翻译
                MessageType.ERROR,        # ✅ 显示错误
                MessageType.WARNING,      # ✅ 显示警告
                MessageType.USER_ALERT,   # ✅ 显示用户提示
                # ❌ 不包含 STATUS - 状态信息不显示在控制台
                # ❌ 不包含 DEBUG - Token 用量不显示
            ]
        )
        manager.add_handler(console_handler)

        # 2. 添加日志文件处理器（记录到文件，不显示在控制台）
        log_file_handler = LogFileHandler(
            logger_name="meeting_translator",
            enabled_types=[
                MessageType.TRANSLATION,      # ✅ 翻译结果（完整记录）
                MessageType.SUBTITLE,          # ✅ 字幕翻译（完整记录）    
                MessageType.STATUS,           # ✅ 状态信息
                MessageType.ERROR,            # ✅ 错误
                MessageType.WARNING,          # ✅ 警告
                MessageType.DEBUG,            # ✅ 调试信息（Token 用量等）
                MessageType.USER_ALERT        # ✅ 用户提示（弹窗内容记录到日志）
            ]
        )
        manager.add_handler(log_file_handler)

        # 3. 添加用户提示处理器（显示 QMessageBox 弹窗）
        alert_handler = AlertHandler(
            parent_widget=self,  # 使用主窗口作为父窗口
            show_dialog=True     # 启用弹窗显示
        )
        manager.add_handler(alert_handler)

        # 注意：SubtitleHandler 会在字幕窗口创建后添加
        # （见 _start_listen_mode 方法）

    def _update_subtitle_handler(self):
        """更新或创建 SubtitleHandler"""
        manager = Out

        # 如果字幕窗口已存在，添加 SubtitleHandler
        if self.subtitle_window:
            # 检查是否已有 SubtitleHandler
            has_subtitle_handler = any(
                isinstance(h, SubtitleHandler) for h in manager.handlers
            )

            if not has_subtitle_handler:
                # 创建 SubtitleHandler，self 作为 parent（确保正确的线程亲和性）
                subtitle_handler = SubtitleHandler(self.subtitle_window)
                manager.add_handler(subtitle_handler)

    def load_stylesheet(self):
        """加载 QSS 样式表"""
        style_path = os.path.join(os.path.dirname(__file__), "styles", "modern_style.qss")
        try:
            with open(style_path, 'r', encoding='utf-8') as f:
                stylesheet = f.read()
                self.setStyleSheet(stylesheet)
                Out.status("已加载现代化样式表")
        except Exception as e:
            Out.warning(f"无法加载样式表: {e}，使用默认样式")

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("🎙️ 会议翻译工具")
        self.setGeometry(100, 100, 700, 600)
        self.setObjectName("MainWindow")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 1. 模式选择组
        mode_group = QGroupBox("🎯 翻译模式")
        mode_layout = QHBoxLayout()

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("👂 听 - 会议音频→中文字幕", TranslationMode.LISTEN)
        self.mode_combo.addItem("🎤 说 - 中文麦克风→英文虚拟麦克风", TranslationMode.SPEAK)
        self.mode_combo.addItem("🔄 双向 - 同时运行听+说", TranslationMode.BIDIRECTIONAL)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)

        mode_label = QLabel("选择模式:")
        mode_label.setObjectName("subtitleLabel")
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo, 1)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # 1.5 API 提供商选择组
        provider_group = QGroupBox("🌐 API 提供商")
        provider_layout = QHBoxLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("阿里云 Qwen (Alibaba Cloud)", "aliyun")
        self.provider_combo.addItem("豆包 Doubao (ByteDance)", "doubao")
        self.provider_combo.addItem("OpenAI Realtime", "openai")
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)

        provider_label = QLabel("选择提供商:")
        provider_label.setObjectName("subtitleLabel")
        provider_layout.addWidget(provider_label)
        provider_layout.addWidget(self.provider_combo, 1)

        self.provider_info = QLabel("当前: 阿里云 Qwen")
        self.provider_info.setObjectName("deviceInfoLabel")
        provider_layout.addWidget(self.provider_info)

        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # 2. 音频设备选择组
        device_group = QGroupBox("🎧 音频设备")
        device_layout = QVBoxLayout()
        device_layout.setSpacing(16)

        # 2.1 听模式设备（会议音频输入）
        self.listen_device_widget = QWidget()
        listen_layout = QVBoxLayout()
        listen_label = QLabel("🔊 会议音频输入（听模式）:")
        listen_label.setObjectName("subtitleLabel")
        listen_layout.addWidget(listen_label)
        self.listen_device_combo = QComboBox()
        self.listen_device_combo.currentIndexChanged.connect(self.on_listen_device_selected)

        # 输入下拉框 + 刷新按钮（右侧）
        self.listen_device_row_layout = QHBoxLayout()
        self.listen_device_row_layout.setSpacing(8)
        self.listen_device_row_layout.addWidget(self.listen_device_combo, 1)
        listen_layout.addLayout(self.listen_device_row_layout)
        self.listen_device_info = QLabel("请选择设备")
        self.listen_device_info.setObjectName("deviceInfoLabel")
        listen_layout.addWidget(self.listen_device_info)
        listen_layout.setContentsMargins(0, 0, 0, 10)
        self.listen_device_widget.setLayout(listen_layout)
        device_layout.addWidget(self.listen_device_widget)

        # 2.2 说模式设备（中文麦克风 + 英文虚拟麦克风）
        self.speak_device_widget = QWidget()
        speak_layout = QVBoxLayout()
        speak_layout.setSpacing(8)

        # 中文麦克风输入
        speak_input_label = QLabel("🎤 中文麦克风（说模式）:")
        speak_input_label.setObjectName("subtitleLabel")
        speak_layout.addWidget(speak_input_label)
        self.speak_input_combo = QComboBox()
        self.speak_input_combo.currentIndexChanged.connect(self.on_speak_device_selected)

        # 输入下拉框 + 刷新按钮（右侧）
        self.speak_input_row_layout = QHBoxLayout()
        self.speak_input_row_layout.setSpacing(8)
        self.speak_input_row_layout.addWidget(self.speak_input_combo, 1)
        speak_layout.addLayout(self.speak_input_row_layout)

        # 英文虚拟麦克风输出
        speak_output_label = QLabel("🔊 英文虚拟麦克风输出（VB-Cable）:")
        speak_output_label.setObjectName("subtitleLabel")
        speak_layout.addWidget(speak_output_label)
        self.speak_output_combo = QComboBox()
        self.speak_output_combo.currentIndexChanged.connect(self.on_speak_device_selected)
        speak_layout.addWidget(self.speak_output_combo)

        # 英文语音音色选择
        voice_label = QLabel("🎭 英文语音音色:")
        voice_label.setObjectName("subtitleLabel")
        speak_layout.addWidget(voice_label)

        # 音色选择和试听按钮的布局
        voice_control_layout = QHBoxLayout()
        voice_control_layout.setSpacing(8)
        voice_control_layout.setAlignment(Qt.AlignTop)  # 顶部对齐

        self.voice_combo = QComboBox()
        # 注意：音色选项会在 _load_provider_voices() 中动态加载
        self.voice_combo.currentIndexChanged.connect(self.on_voice_changed)
        voice_control_layout.addWidget(self.voice_combo)

        # 音色试听按钮（与dropdown等高等大）
        self.voice_preview_btn = QPushButton("▶ 试听")
        self.voice_preview_btn.setMinimumHeight(32)  # 与ComboBox默认高度一致
        self.voice_preview_btn.setMinimumWidth(80)   # 增加宽度
        self.voice_preview_btn.setToolTip("试听当前音色")
        self.voice_preview_btn.setObjectName("iconButton")
        self.voice_preview_btn.clicked.connect(self.on_voice_preview_clicked)
        voice_control_layout.addWidget(self.voice_preview_btn)

        speak_layout.addLayout(voice_control_layout)

        # 音色播放器（用于停止播放）
        self.voice_player = None
        self._voice_preview_stop_flag = False
        self._voice_preview_signals = VoicePreviewSignals()
        self._voice_preview_signals.finished.connect(self._on_voice_preview_finished)

        self.speak_device_info = QLabel("请选择设备")
        self.speak_device_info.setObjectName("deviceInfoLabel")
        speak_layout.addWidget(self.speak_device_info)
        speak_layout.setContentsMargins(0, 0, 0, 0)

        self.speak_device_widget.setLayout(speak_layout)
        self.speak_device_widget.hide()  # 默认隐藏
        device_layout.addWidget(self.speak_device_widget)

        # 刷新设备按钮
        self.refresh_devices_btn = QPushButton("🔄 刷新设备列表")
        self.refresh_devices_btn.setObjectName("secondaryButton")
        self.refresh_devices_btn.clicked.connect(self.on_refresh_devices)

        # 默认放到听模式输入的右侧（后续会在 on_mode_changed 中动态移动）
        self.listen_device_row_layout.addWidget(self.refresh_devices_btn)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # 控制按钮组
        control_group = QGroupBox("⚙️ 控制")
        control_layout = QHBoxLayout()
        control_layout.setSpacing(12)

        # 启动/停止按钮
        self.start_btn = QPushButton("▶️ 启动翻译")
        self.start_btn.clicked.connect(self.toggle_translation)
        control_layout.addWidget(self.start_btn)

        # 显示/隐藏字幕窗口
        self.subtitle_btn = QPushButton("📺 字幕窗口")
        self.subtitle_btn.setObjectName("secondaryButton")
        self.subtitle_btn.setEnabled(False)
        self.subtitle_btn.clicked.connect(self.toggle_subtitle_window)
        control_layout.addWidget(self.subtitle_btn)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # 状态显示组
        status_group = QGroupBox("📊 状态")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("● 就绪")
        self.status_label.setObjectName("statusLabel")
        self.update_status("就绪", "ready")
        status_layout.addWidget(self.status_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # 帮助信息
        help_label = QLabel("""
        <b>📖 使用说明:</b><br>
        <b>👂 听模式</b>: 捕获会议音频（英文）→显示中文字幕（适合听英文会议）<br>
        <b>🎤 说模式</b>: 捕获中文麦克风→输出英文到虚拟麦克风（适合说中文参会）<br>
        <b>🔄 双向模式</b>: 同时运行听+说（完整双向同传）<br>
        <br>
        <b>💡 提示:</b> 说模式需要安装 VB-Audio Cable 虚拟音频设备
        """)
        help_label.setWordWrap(True)
        help_label.setObjectName("infoLabel")
        layout.addWidget(help_label)

        self.setLayout(layout)

    def update_status(self, text, status_type="ready"):
        """更新状态显示"""
        status_map = {
            "ready": ("statusReady", "● "),
            "running": ("statusRunning", "● "),
            "error": ("statusError", "● ")
        }
        object_name, prefix = status_map.get(status_type, ("statusReady", "● "))
        self.status_label.setObjectName(object_name)
        self.status_label.setText(prefix + text)
        # 强制更新样式
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def on_mode_changed(self, index):
        """模式切换事件"""
        self.current_mode = self.mode_combo.itemData(index)

        # 保存模式配置（仅在非加载期间）
        if not self.is_loading_config:
            self.config_manager.set_mode(self.current_mode.value)

        # 切换设备选择界面
        if self.current_mode == TranslationMode.LISTEN:
            self.listen_device_widget.show()
            self.speak_device_widget.hide()
        elif self.current_mode == TranslationMode.SPEAK:
            self.listen_device_widget.hide()
            self.speak_device_widget.show()
        else:  # BIDIRECTIONAL
            self.listen_device_widget.show()
            self.speak_device_widget.show()

        self._update_refresh_button_location()
        Out.status(f"切换到模式: {self.current_mode.value}")

    def _update_refresh_button_location(self):
        """将刷新按钮放到当前可见的输入设备下拉框右侧。"""
        if not hasattr(self, "refresh_devices_btn"):
            return

        # 先从可能存在的布局里移除，避免占位/重复
        for layout in (
            getattr(self, "listen_device_row_layout", None),
            getattr(self, "speak_input_row_layout", None),
        ):
            if layout is not None:
                layout.removeWidget(self.refresh_devices_btn)

        if self.current_mode == TranslationMode.SPEAK:
            target_layout = getattr(self, "speak_input_row_layout", None)
        else:
            # LISTEN / BIDIRECTIONAL：优先放到「会议音频输入」右侧
            target_layout = getattr(self, "listen_device_row_layout", None)

        if target_layout is not None:
            target_layout.addWidget(self.refresh_devices_btn)

    def on_listen_device_selected(self, index):
        """听模式设备选择事件"""
        device = self.listen_device_combo.itemData(index)
        if device:
            info_parts = [
                f"API: {device.get('host_api', 'Unknown')}",
                f"采样率: {device['sample_rate']} Hz",
                f"声道: {device['channels']}"
            ]
            if device.get('is_wasapi_loopback'):
                info_parts.append("⭐ WASAPI Loopback（推荐）")
            info_text = " | ".join(info_parts)
            self.listen_device_info.setText(info_text)

            # 保存设备配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_listen_device_display(device['display_name'])

    def on_speak_device_selected(self, index):
        """说模式设备选择事件"""
        input_device = self.speak_input_combo.currentData()
        output_device = self.speak_output_combo.currentData()

        if input_device and output_device:
            info_parts = [
                f"输入: {input_device['sample_rate']}Hz",
                f"输出: {output_device['sample_rate']}Hz"
            ]
            if 'CABLE' in output_device['name'] or 'VoiceMeeter' in output_device['name']:
                info_parts.append("⭐ 虚拟音频设备（推荐）")
            info_text = " | ".join(info_parts)
            self.speak_device_info.setText(info_text)

        # 保存设备配置（仅在非加载期间）
        if not self.is_loading_config:
            if input_device:
                self.config_manager.set_speak_input_device_display(input_device['display_name'])
            if output_device:
                self.config_manager.set_speak_output_device_display(output_device['display_name'])

    def on_voice_changed(self, index):
        """语音音色选择事件"""
        # 停止正在播放的音色样本
        self._stop_voice_preview()

        voice = self.voice_combo.itemData(index)
        if voice is not None:  # 允许空字符串（豆包不支持音色）
            # 保存语音配置（仅在非加载期间），传递当前 provider
            if not self.is_loading_config:
                self.config_manager.set_voice(voice, provider=self.provider)
                Out.status(f"已保存音色设置: {self.provider} -> {voice or '(默认)'}")

    def _stop_voice_preview(self):
        """停止音色样本播放"""
        if self.voice_player and self.voice_player.is_alive():
            # 设置停止标志
            self._voice_preview_stop_flag = True
            # 等待线程结束（最多1秒）
            self.voice_player.join(timeout=1.0)
            self.voice_player = None

        # 恢复按钮状态
        self.voice_preview_btn.setText("▶ 试听")
        self._voice_preview_stop_flag = False

    def on_voice_preview_clicked(self):
        """音色试听按钮点击事件"""
        # 如果正在播放，停止播放
        if self.voice_player and self.voice_player.is_alive():
            self._stop_voice_preview()
            return

        # 获取当前选中的音色
        voice = self.voice_combo.currentData()
        if not voice:
            Out.warning("当前提供商不支持音色选择")
            return

        # 构建音色样本文件路径
        from pathlib import Path
        from paths import VOICE_SAMPLES_DIR

        provider_prefix = {
            "aliyun": "qwen",
            "openai": "openai",
            "doubao": "doubao"
        }.get(self.provider)

        if not provider_prefix:
            Out.warning(f"提供商 {self.provider} 不支持音色试听")
            return

        filename = f"{provider_prefix}_{voice}.wav"
        filepath = VOICE_SAMPLES_DIR / filename

        if not filepath.exists():
            Out.warning(f"音色样本文件不存在: {filename}")
            return

        # 更新按钮状态（保持可点击）
        self.voice_preview_btn.setText("⏸ 停止")

        # 在后台线程播放音频
        self._voice_preview_stop_flag = False
        import threading
        self.voice_player = threading.Thread(
            target=self._play_voice_sample_thread,
            args=(str(filepath),),
            daemon=True
        )
        self.voice_player.start()

    def _play_voice_sample_thread(self, filepath: str):
        """
        在后台线程播放音色样本（支持停止）

        Args:
            filepath: 音色样本文件路径
        """
        try:
            import wave
            import pyaudio

            # 打开 WAV 文件
            wf = wave.open(filepath, 'rb')

            # 创建 PyAudio 实例
            p = pyaudio.PyAudio()

            # 打开音频流
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )

            # 读取并播放音频数据
            chunk_size = 1024
            data = wf.readframes(chunk_size)

            while len(data) > 0 and not self._voice_preview_stop_flag:
                stream.write(data)
                data = wf.readframes(chunk_size)

            # 清理资源
            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()

            if self._voice_preview_stop_flag:
                Out.status("音色试听已停止")

        except Exception as e:
            Out.error(f"播放音色样本时出错: {e}")
        finally:
            # 发送完成信号（在主线程中恢复按钮状态）
            self._voice_preview_signals.finished.emit()
            self.voice_player = None

    def _on_voice_preview_finished(self):
        """音色试听完成槽函数（在主线程中执行）"""
        self.voice_preview_btn.setText("▶ 试听")

    def _load_provider_voices(self):
        """
        加载当前 provider 支持的音色列表
        并恢复该 provider 的音色配置
        """
        # 临时设置加载标志，防止触发 on_voice_changed 时保存默认值
        was_loading = self.is_loading_config
        self.is_loading_config = True

        try:
            from translation_client_factory import TranslationClientFactory

            self.voice_combo.clear()

            # 获取该 provider 支持的音色
            voices = TranslationClientFactory.get_supported_voices(self.provider)

            if not voices:
                # 如果 provider 不支持音色（如豆包），显示提示
                self.voice_combo.addItem("该提供商不支持音色选择", "")
                self.voice_combo.setEnabled(False)
                Out.status(f"{self.provider} 不支持音色选择")
                return

            # 启用音色选择
            self.voice_combo.setEnabled(True)

            # 添加所有支持的音色
            for voice_id, voice_name in voices.items():
                self.voice_combo.addItem(voice_name, voice_id)

            # 恢复该 provider 的音色配置
            saved_voice = self.config_manager.get_voice(provider=self.provider)
            if saved_voice:
                # 在新列表中查找并恢复
                for i in range(self.voice_combo.count()):
                    if self.voice_combo.itemData(i) == saved_voice:
                        self.voice_combo.setCurrentIndex(i)
                        Out.status(f"恢复音色设置: {self.provider} -> {saved_voice}")
                        break
            else:
                # 如果没有保存的配置，选择第一个
                if self.voice_combo.count() > 0:
                    self.voice_combo.setCurrentIndex(0)
        finally:
            # 恢复原来的加载状态
            self.is_loading_config = was_loading

    def on_provider_changed(self, index):
        """API 提供商选择事件"""
        new_provider = self.provider_combo.itemData(index)
        if new_provider and new_provider != self.provider:
            old_provider = self.provider

            # 停止正在播放的音色样本
            self._stop_voice_preview()

            # 检查依赖（针对需要特定依赖的提供商）
            if new_provider == "doubao":
                from doubao_client import DoubaoClient
                is_available, error_msg = DoubaoClient.check_dependencies()
                if not is_available:
                    # 使用 OutputManager 显示错误提示
                    Out.user_alert(
                        message=error_msg,
                        title="依赖缺失"
                    )

                    # 回滚到原来的提供商
                    # 找到原来提供商的索引
                    for i in range(self.provider_combo.count()):
                        if self.provider_combo.itemData(i) == old_provider:
                            self.provider_combo.setCurrentIndex(i)
                            Out.warning(f"依赖缺失，已回滚到原提供商: {old_provider}")
                            return

            # 更新提供商
            self.provider = new_provider
            provider_name = self.provider_combo.currentText()
            self.provider_info.setText(f"当前: {provider_name}")

            # 重新加载该提供商支持的语音音色
            self._load_provider_voices()

            # 保存提供商配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_provider(self.provider)
                Out.status(f"已切换 API 提供商: {provider_name} ({new_provider})")

    def on_refresh_devices(self):
        """刷新设备列表"""
        Out.status("正在刷新设备列表...")

        # 保存当前选中的设备
        current_listen_device = self.listen_device_combo.currentData()
        current_speak_input_device = self.speak_input_combo.currentData()
        current_speak_output_device = self.speak_output_combo.currentData()

        # 重新扫描设备
        try:
            self.device_manager.refresh()
            Out.status("设备扫描完成")
        except Exception as e:
            Out.error(f"刷新设备失败: {e}")
            return

        # 重新加载设备列表
        self.load_devices()

        # 尝试恢复之前选中的设备（通过 display_name 匹配）
        restored = False
        if current_listen_device:
            for i in range(self.listen_device_combo.count()):
                device = self.listen_device_combo.itemData(i)
                if device and device['display_name'] == current_listen_device['display_name']:
                    self.listen_device_combo.setCurrentIndex(i)
                    Out.status(f"✓ 恢复听模式设备: {current_listen_device['display_name']}")
                    restored = True
                    break
            if not restored:
                Out.warning(f"⚠ 未找到之前的听模式设备: {current_listen_device['display_name']}")

        restored = False
        if current_speak_input_device:
            for i in range(self.speak_input_combo.count()):
                device = self.speak_input_combo.itemData(i)
                if device and device['display_name'] == current_speak_input_device['display_name']:
                    self.speak_input_combo.setCurrentIndex(i)
                    Out.status(f"✓ 恢复说模式输入设备: {current_speak_input_device['display_name']}")
                    restored = True
                    break
            if not restored:
                Out.warning(f"⚠ 未找到之前的说模式输入设备: {current_speak_input_device['display_name']}")

        restored = False
        if current_speak_output_device:
            for i in range(self.speak_output_combo.count()):
                device = self.speak_output_combo.itemData(i)
                if device and device['display_name'] == current_speak_output_device['display_name']:
                    self.speak_output_combo.setCurrentIndex(i)
                    Out.status(f"✓ 恢复说模式输出设备: {current_speak_output_device['display_name']}")
                    restored = True
                    break
            if not restored:
                Out.warning(f"⚠ 未找到之前的说模式输出设备: {current_speak_output_device['display_name']}")

        Out.status("设备列表刷新完成")

    def load_devices(self):
        """加载音频设备列表"""
        # 1. 加载听模式设备（真实 loopback/speaker，用于 s2t 采集）
        # 使用 get_real_speakers() 只返回 loopback 设备
        speaker_devices = self.device_manager.get_real_speakers()
        self.listen_device_combo.clear()

        for device in speaker_devices:
            # 使用 display_name（已包含 host api）
            display_name = device.get('display_name', device['name'])
            if device.get('is_wasapi_loopback'):
                display_name += " [推荐]"
            self.listen_device_combo.addItem(display_name, device)

        # 自动选择推荐设备
        self._auto_select_loopback(self.listen_device_combo)

        # 2. 加载说模式输入设备（真实麦克风，用于 s2s 采集）
        # 使用 get_real_microphones() 只返回真实 mic
        mic_devices = self.device_manager.get_real_microphones()
        self.speak_input_combo.clear()

        for device in mic_devices:
            # 使用 display_name（已包含 host api）
            display_name = device.get('display_name', device['name'])
            self.speak_input_combo.addItem(display_name, device)

        # 3. 加载说模式输出设备（包含虚拟和真实输出，便于选择输出到耳机/音箱）
        all_output_devices = self.device_manager.get_output_devices(include_voicemeeter=True, deduplicate=True)
        self.speak_output_combo.clear()

        for device in all_output_devices:
            # 使用 display_name（已包含 host api）
            display_name = device.get('display_name', device['name'])

            # 标记虚拟/物理属性
            if device.get('is_virtual'):
                display_name += " [虚拟]"

            # 标记推荐的 API（WASAPI 或 MME，排除 DirectSound）
            host_api = device.get('host_api', '')
            if 'WASAPI' in host_api:
                display_name += " [推荐]"
            elif 'MME' in host_api:
                display_name += " [可用]"

            self.speak_output_combo.addItem(display_name, device)

        # 自动选择最佳设备（优先虚拟，其次推荐 API，最后任何可用输出）
        self._auto_select_virtual_output(self.speak_output_combo)

    def _auto_select_loopback(self, combo: QComboBox):
        """自动选择 Loopback 设备"""
        # 优先选择 WASAPI Loopback
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_wasapi_loopback'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择 WASAPI Loopback: {device['name']}")
                return

        # 次选传统 loopback
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_loopback'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择 Loopback: {device['name']}")
                return

    def _auto_select_virtual_output(self, combo: QComboBox):
        """自动选择输出设备（优先虚拟，其次推荐 API，最后任何设备）"""
        # 1) 优先选择虚拟 + WASAPI
        for i in range(combo.count()):
            device = combo.itemData(i)
            host_api = device.get('host_api', '')
            if device.get('is_virtual') and 'WASAPI' in host_api:
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出 (WASAPI): {device.get('display_name', device['name'])}")
                return

        # 2) 次选虚拟 + MME
        for i in range(combo.count()):
            device = combo.itemData(i)
            host_api = device.get('host_api', '')
            if device.get('is_virtual') and 'MME' in host_api:
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出 (MME): {device.get('display_name', device['name'])}")
                return

        # 3) 再次次选：任意虚拟设备
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_virtual'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出: {device.get('display_name', device['name'])}")
                return

        # 4) 最后备选：任何设备（允许用户直接输出到耳机/音箱）
        if combo.count() > 0:
            combo.setCurrentIndex(0)
            device = combo.itemData(0)
            Out.status(f"自动选择输出设备: {device.get('display_name', device['name'])}")

    def load_config(self):
        """加载保存的配置"""
        Out.status("=" * 60)
        Out.status("开始加载上次保存的配置...")

        # 显示所有配置项（用于调试）
        Out.status(f"  模式: {self.config_manager.get_mode()}")
        Out.status(f"  提供商: {self.config_manager.get_provider()}")
        Out.status(f"  听模式设备: {self.config_manager.get_listen_device_display() or '未设置'}")
        Out.status(f"  说模式输入: {self.config_manager.get_speak_input_device_display() or '未设置'}")
        Out.status(f"  说模式输出: {self.config_manager.get_speak_output_device_display() or '未设置'}")
        Out.status(f"  语音音色: {self.config_manager.get_voice()}")

        # 1. 恢复翻译模式
        saved_mode = self.config_manager.get_mode()
        for i in range(self.mode_combo.count()):
            mode = self.mode_combo.itemData(i)
            if mode.value == saved_mode:
                self.mode_combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复模式: {saved_mode}")
                break

        # 2. 恢复 API 提供商
        saved_provider = self.config_manager.get_provider()
        for i in range(self.provider_combo.count()):
            provider = self.provider_combo.itemData(i)
            if provider == saved_provider:
                self.provider_combo.setCurrentIndex(i)
                self.provider = saved_provider
                provider_name = self.provider_combo.currentText()
                self.provider_info.setText(f"当前: {provider_name}")
                Out.status(f"✓ 恢复 API 提供商: {saved_provider}")
                break

        # 2.5 加载该 provider 的音色列表并恢复音色设置
        self._load_provider_voices()

        # 3. 恢复听模式设备（通过 display_name 匹配）
        # 不管当前模式，都恢复所有模式的配置
        listen_device_display = self.config_manager.get_listen_device_display()
        if listen_device_display:
            self._select_device_by_display(self.listen_device_combo, listen_device_display, "听模式设备")

        # 4. 恢复说模式输入设备
        speak_input_display = self.config_manager.get_speak_input_device_display()
        if speak_input_display:
            self._select_device_by_display(self.speak_input_combo, speak_input_display, "说模式输入设备")

        # 5. 恢复说模式输出设备
        speak_output_display = self.config_manager.get_speak_output_device_display()
        if speak_output_display:
            self._select_device_by_display(self.speak_output_combo, speak_output_display, "说模式输出设备")

        # 注意：语音音色已在 _load_provider_voices() 中恢复

        Out.status("配置加载完成")

    def _check_and_generate_voice_samples(self):
        """
        检查并生成缺失的音色样本文件（阻塞式）

        在程序启动前同步生成所有缺失的音色样本，确保进入程序时样本齐全。
        """
        from translation_client_factory import TranslationClientFactory
        from voice_sample_generator import generate_provider_samples

        try:
            # 获取当前配置的 provider
            provider = self.config_manager.get_provider()

            # 豆包不支持音色选择，跳过
            if provider == "doubao":
                return

            # 获取该 provider 支持的音色列表
            supported_voices = TranslationClientFactory.get_supported_voices(provider)

            if not supported_voices:
                return

            # 生成缺失的音色样本
            generate_provider_samples(provider, TranslationClientFactory, supported_voices)

        except Exception as e:
            print(f"检查音色样本时出错: {e}\n")

    def _select_device_by_display(self, combo: QComboBox, device_display: str, device_type: str):
        """通过设备显示名称（包含 host api）选择设备"""
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device and device['display_name'] == device_display:
                combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复{device_type}: {device_display}")
                return
        Out.warning(f"⚠ 未找到{device_type}: {device_display}（设备可能已变化，使用默认值）")

    def toggle_translation(self):
        """启动/停止翻译"""
        if not self.is_running:
            self.start_translation()
        else:
            self.stop_translation()

    def start_translation(self):
        """启动翻译（根据模式）"""
        Out.status(f"启动翻译（模式：{self.current_mode.value}）...")
        self.update_status("正在启动...", "running")

        try:
            if self.current_mode == TranslationMode.LISTEN:
                self._start_listen_mode()
            elif self.current_mode == TranslationMode.SPEAK:
                self._start_speak_mode()
            else:  # BIDIRECTIONAL
                self._start_listen_mode()
                self._start_speak_mode()
        except Exception as e:
            Out.error(f"启动翻译失败: {e}", exc_info=True)
            # 恢复 UI 状态
            self.update_status(f"启动失败: {str(e)}", "error")
            # 清理可能已启动的组件
            self.stop_translation(save_subtitles=False)
            return

        try:

            # 更新 UI
            self.is_running = True
            self.start_btn.setText("⏹️ 停止翻译")
            self.start_btn.setObjectName("stopButton")
            # 强制重新应用样式
            self.start_btn.style().unpolish(self.start_btn)
            self.start_btn.style().polish(self.start_btn)

            self.mode_combo.setEnabled(False)
            self.listen_device_combo.setEnabled(False)
            self.speak_input_combo.setEnabled(False)
            self.speak_output_combo.setEnabled(False)

            # 字幕窗口按钮：只在听模式和双向模式下启用
            has_subtitle = self.current_mode in [TranslationMode.LISTEN, TranslationMode.BIDIRECTIONAL]
            self.subtitle_btn.setEnabled(has_subtitle)

            self.update_status("翻译进行中...", "running")

            Out.status("翻译已启动")

        except Exception as e:
            Out.error(f"启动翻译失败: {e}")
            import traceback
            traceback.print_exc()
            self.update_status(f"启动失败: {str(e)}", "error")

            # 清理
            self.stop_translation(save_subtitles=False)

    def _start_listen_mode(self):
        """启动听模式（会议音频→中文字幕）"""
        Out.status("启动听模式...")

        # 获取设备
        device = self.listen_device_combo.currentData()
        if not device:
            raise ValueError("请先选择会议音频输入设备")

        # 1. 创建字幕窗口
        if not self.subtitle_window:
            self.subtitle_window = SubtitleWindow()
        self.subtitle_window.show()

        # 2. 添加 SubtitleHandler 到 OutputManager
        self._update_subtitle_handler()

        # 3. 启动翻译服务（英→中，仅字幕）
        self.listen_translation_service = MeetingTranslationServiceWrapper(
            api_key=None,  # 让工厂方法根据 provider 自动获取 API Key
            source_language="en",
            target_language="zh",
            audio_enabled=False,  # 仅字幕
            provider=self.provider  # 使用当前选择的 provider
        )
        self.listen_translation_service.start()

        # 3. 启动音频捕获（会议音频）
        device_sample_rate = device['sample_rate']
        device_channels = device['channels']

        Out.status(f"听模式设备: {device['name']}, {device_sample_rate}Hz, {device_channels}声道")

        self.listen_audio_capture = AudioCaptureThread(
            device_index=device['index'],
            on_audio_chunk=self.listen_translation_service.send_audio_chunk,
            sample_rate=device_sample_rate,
            channels=device_channels,
            target_sample_rate=16000,
            target_channels=1
        )
        self.listen_audio_capture.start()

        Out.status("听模式已启动")

    def _start_speak_mode(self):
        """启动说模式（中文麦克风→英文虚拟麦克风）"""
        Out.status("启动说模式...")

        # 获取设备
        input_device = self.speak_input_combo.currentData()
        output_device = self.speak_output_combo.currentData()

        if not input_device:
            raise ValueError("请先选择中文麦克风")
        if not output_device:
            raise ValueError("请先选择英文虚拟麦克风输出设备")

        # 1. 启动音频输出线程（虚拟麦克风）
        # 使用自适应变速功能，在队列堆积时自动加速播放
        try:
            Out.status("正在创建音频输出线程...")

            # 根据 provider 获取正确的输出采样率
            api_output_rate = self.PROVIDER_OUTPUT_RATES.get(self.provider, 24000)
            Out.status(f"API 音频输出采样率: {api_output_rate} Hz (provider={self.provider})")

            self.speak_audio_output = AudioOutputThread(
                device_index=output_device['index'],
                input_sample_rate=api_output_rate,  # API 输出采样率（根据 provider）
                output_sample_rate=output_device['sample_rate'],  # 使用设备的采样率（通常是44100），由 AudioOutputThread 自动重采样
                channels=output_device['channels'],  # 使用设备的实际声道数（通常是2）
                enable_dynamic_speed=True,  # 启用自适应变速
                max_speed=2.0,  # 最高2倍速
                queue_threshold=20,  # 队列低于20正常播放
                target_catchup_time=10.0,  # 10秒内追上进度
                max_chunks_per_batch=50  # 单次最多处理50个chunks
            )
            Out.status("音频输出线程已创建，正在启动...")
            self.speak_audio_output.start()
            Out.status("音频输出线程启动成功")
        except Exception as e:
            Out.error(f"启动音频输出线程失败: {e}", exc_info=True)
            raise

        # 2. 启动翻译服务（中→英，音频输出）
        # 获取用户选择的音色
        selected_voice = self.voice_combo.currentData()  # "Cherry" 或 "Nofish"

        try:
            Out.status("正在创建翻译服务...")
            self.speak_translation_service = MeetingTranslationServiceWrapper(
                api_key=None,  # 让工厂方法根据 provider 自动获取 API Key
                source_language="zh",
                target_language="en",
                audio_enabled=True,  # 启用音频
                voice=selected_voice,
                provider=self.provider,  # 使用当前选择的 provider
                on_audio_chunk=self.speak_audio_output.write_audio_chunk  # 写入虚拟麦克风
            )
            Out.status("翻译服务已创建，正在启动...")
            self.speak_translation_service.start()
            Out.status("翻译服务启动成功")
        except Exception as e:
            Out.error(f"启动翻译服务失败: {e}", exc_info=True)
            # 清理已启动的音频输出
            if self.speak_audio_output:
                try:
                    self.speak_audio_output.stop()
                except:
                    pass
            raise

        # 3. 启动音频捕获（中文麦克风）
        input_sample_rate = input_device['sample_rate']
        input_channels = input_device['channels']

        Out.status(f"说模式输入: {input_device['name']}, {input_sample_rate}Hz, {input_channels}声道")
        Out.status(f"说模式输出: {output_device['name']}")
        Out.status(f"英文语音音色: {selected_voice}")

        try:
            Out.status("正在创建音频捕获线程...")
            self.speak_audio_capture = AudioCaptureThread(
                device_index=input_device['index'],
                on_audio_chunk=self.speak_translation_service.send_audio_chunk,
                sample_rate=input_sample_rate,
                channels=input_channels,
                target_sample_rate=16000,
                target_channels=1
            )
            Out.status("音频捕获线程已创建，正在启动...")
            self.speak_audio_capture.start()
            Out.status("音频捕获线程启动成功")
        except Exception as e:
            Out.error(f"启动音频捕获失败: {e}", exc_info=True)
            # 清理已启动的组件
            if self.speak_translation_service:
                try:
                    self.speak_translation_service.stop()
                except:
                    pass
            if self.speak_audio_output:
                try:
                    self.speak_audio_output.stop()
                except:
                    pass
            raise

        Out.status("说模式已启动")

    def stop_translation(self, save_subtitles=True):
        """
        停止翻译

        Args:
            save_subtitles: 是否保存字幕（默认True）
        """
        Out.status("停止翻译...")

        # 1. 保存字幕（如果有内容）
        # todo: 需要保存的应该是完整的会议记录----包括s2s和s2t。因此也许不应该在subtitle_window.py中保存。
        # 可以考虑直接做一个record_file_handler，利用OutputMgr框架。
        if save_subtitles and self.subtitle_window:
            try:
                # 使用新的路径结构
                save_dir = RECORDS_DIR
                filepath = self.subtitle_window.save_subtitles(save_dir)
                if filepath:
                    Out.status(f"✅ 字幕已保存: {filepath}")
                    self.update_status(f"已保存到: {os.path.basename(filepath)}", "ready")
            except Exception as e:
                Out.error(f"保存字幕失败: {e}")

        # 2. 停止听模式
        try:
            if self.listen_audio_capture:
                self.listen_audio_capture.stop()
                self.listen_audio_capture = None
        except Exception as e:
            Out.error(f"停止音频捕获时出错: {e}")

        try:
            if self.listen_translation_service:
                self.listen_translation_service.stop()
                self.listen_translation_service = None
        except Exception as e:
            Out.error(f"停止翻译服务时出错: {e}")

        # 3. 停止说模式
        try:
            if self.speak_audio_capture:
                self.speak_audio_capture.stop()
                self.speak_audio_capture = None
        except Exception as e:
            Out.error(f"停止说模式音频捕获时出错: {e}")

        try:
            if self.speak_translation_service:
                self.speak_translation_service.stop()
                self.speak_translation_service = None
        except Exception as e:
            Out.error(f"停止说模式翻译服务时出错: {e}")

        try:
            if self.speak_audio_output:
                self.speak_audio_output.stop()
                self.speak_audio_output = None
        except Exception as e:
            Out.error(f"停止音频输出时出错: {e}")

        # 4. 更新 UI
        self.is_running = False

        try:
            self.start_btn.setText("▶️ 启动翻译")
            self.start_btn.setObjectName("")  # 移除stopButton，恢复默认样式
            # 强制重新应用样式
            self.start_btn.style().unpolish(self.start_btn)
            self.start_btn.style().polish(self.start_btn)

            self.mode_combo.setEnabled(True)
            self.listen_device_combo.setEnabled(True)
            self.speak_input_combo.setEnabled(True)
            self.speak_output_combo.setEnabled(True)
            self.subtitle_btn.setEnabled(False)

            if not save_subtitles:
                self.update_status("就绪", "ready")
        except Exception as e:
            Out.error(f"更新UI时出错: {e}")
            import traceback
            traceback.print_exc()

        Out.status("翻译已停止")
        Out.status(f"主窗口状态: visible={self.isVisible()}, enabled={self.isEnabled()}")

    def toggle_subtitle_window(self):
        """显示/隐藏字幕窗口"""
        if self.subtitle_window:
            if self.subtitle_window.isVisible():
                self.subtitle_window.hide()
                self.subtitle_btn.setText("📺 字幕窗口")
            else:
                self.subtitle_window.show()
                self.subtitle_btn.setText("🔳 隐藏字幕")

    def closeEvent(self, event):
        """关闭事件"""
        Out.status("主窗口关闭事件被触发")

        # 停止翻译
        self.stop_translation()

        # 停止音色样本播放
        self._stop_voice_preview()

        # 关闭字幕窗口
        if self.subtitle_window:
            self.subtitle_window.close()

        # 清理设备管理器
        if self.device_manager:
            self.device_manager.cleanup()

        Out.status("主窗口即将关闭")
        event.accept()


def exception_hook(exc_type, exc_value, exc_traceback):
    """全局异常处理钩子"""
    if issubclass(exc_type, KeyboardInterrupt):
        # 让 KeyboardInterrupt 正常处理
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # 提供更详细的错误信息
    import traceback

    error_msg = f"未捕获的异常: {exc_type.__name__}"

    if exc_value is not None:
        error_msg += f": {exc_value}"
    else:
        error_msg += " (异常值为 None)"

    # 打印完整的堆栈跟踪
    error_msg += "\n\n堆栈跟踪:"
    error_msg += ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    Out.error(error_msg, exc_info=True)


def main():
    """主函数"""
    # 安装全局异常处理钩子
    sys.excepthook = exception_hook

    try:
        app = QApplication(sys.argv)

        # 创建主窗口
        window = MeetingTranslatorApp()
        window.show()

        Out.status("进入主事件循环")
        exit_code = app.exec_()
        Out.status(f"主事件循环已退出，退出码: {exit_code}")

        sys.exit(exit_code)
    except Exception as e:
        Out.error(f"主函数发生异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
