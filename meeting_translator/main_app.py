"""
会议翻译主应用
整合音频捕获、翻译服务和字幕显示
"""

import sys
import os
import platform
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

from audio_device_manager import AudioDeviceManager
from audio_capture_thread import AudioCaptureThread
from audio_output_thread import AudioOutputThread
from translation_service import MeetingTranslationServiceWrapper
from translation_mode import TranslationMode, ModeConfig
from subtitle_window import SubtitleWindow
from config_manager import ConfigManager

# 配置日志（同时输出到控制台和文件）
import sys
log_dir = os.path.join(os.path.expanduser("~"), "Documents", "会议翻译日志")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"translator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # 控制台输出
        logging.FileHandler(log_file, encoding='utf-8')  # 文件输出
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"日志文件: {log_file}")

# 加载环境变量
load_dotenv()


class TranslationSignals(QObject):
    """翻译信号（用于线程间通信）"""
    translation_received = pyqtSignal(str, str, bool)  # (source_text, target_text, is_final)
    error_occurred = pyqtSignal(str, object)  # (error_message, exception)


class MeetingTranslatorApp(QWidget):
    """会议翻译主应用"""

    def __init__(self):
        super().__init__()

        # 获取翻译服务提供商（默认 aliyun）
        self.provider = os.getenv("TRANSLATION_PROVIDER", "aliyun").lower()
        logger.info(f"翻译服务提供商: {self.provider}")

        # API Key 将由 TranslationClientFactory 根据 provider 自动加载
        # 这样可以确保每个提供商使用正确的 API Key
        self.api_key = None

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

        # 信号
        self.signals = TranslationSignals()
        self.signals.translation_received.connect(self.on_translation_received)
        self.signals.error_occurred.connect(self.on_service_error)

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

    @staticmethod
    def get_virtual_audio_device_name():
        """获取当前平台的虚拟音频设备名称"""
        system = platform.system()
        if system == "Darwin":  # macOS
            return "BlackHole"
        elif system == "Windows":
            return "Voicemeeter"
        else:  # Linux or others
            return "虚拟音频设备"

    @staticmethod
    def get_virtual_audio_device_pattern():
        """获取当前平台用于设备匹配的模式列表"""
        system = platform.system()
        if system == "Darwin":  # macOS
            return ["BlackHole"]
        elif system == "Windows":
            return ["Voicemeeter Input", "VoiceMeeter Input"]
        else:  # Linux or others
            return []

    def load_stylesheet(self):
        """加载 QSS 样式表"""
        import platform
        style_path = os.path.join(os.path.dirname(__file__), "styles", "modern_style.qss")
        try:
            with open(style_path, 'r', encoding='utf-8') as f:
                stylesheet = f.read()

                # 根据操作系统设置字体
                system = platform.system()
                if system == "Darwin":  # macOS
                    # Use Helvetica Neue which handles Chinese and emoji better with bold
                    font_family = '"Helvetica Neue", "PingFang SC", "Apple Color Emoji", sans-serif'
                elif system == "Windows":
                    font_family = '"Microsoft YaHei UI", "Segoe UI Emoji", "Segoe UI", sans-serif'
                else:  # Linux or others
                    font_family = '"Segoe UI", "Noto Color Emoji", sans-serif'

                # 替换样式表中的字体定义
                stylesheet = stylesheet.replace(
                    '"PingFang SC", "Microsoft YaHei UI", "Segoe UI", "Apple Color Emoji", sans-serif',
                    font_family
                )

                self.setStyleSheet(stylesheet)
                logger.info(f"已加载现代化样式表 (字体: {font_family})")
        except Exception as e:
            logger.warning(f"无法加载样式表: {e}，使用默认样式")

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
        listen_layout.addWidget(self.listen_device_combo)
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
        speak_layout.addWidget(self.speak_input_combo)

        # 英文虚拟麦克风输出
        device_name = self.get_virtual_audio_device_name()
        speak_output_label = QLabel(f"🔊 英文虚拟麦克风输出（{device_name}）:")
        speak_output_label.setObjectName("subtitleLabel")
        speak_layout.addWidget(speak_output_label)
        self.speak_output_combo = QComboBox()
        self.speak_output_combo.currentIndexChanged.connect(self.on_speak_device_selected)
        speak_layout.addWidget(self.speak_output_combo)

        # 英文语音音色选择
        voice_label = QLabel("🎭 英文语音音色:")
        voice_label.setObjectName("subtitleLabel")
        speak_layout.addWidget(voice_label)
        self.voice_combo = QComboBox()
        self._load_provider_voices()  # 动态加载提供商支持的声音
        self.voice_combo.currentIndexChanged.connect(self.on_voice_changed)
        speak_layout.addWidget(self.voice_combo)

        self.speak_device_info = QLabel("请选择设备")
        self.speak_device_info.setObjectName("deviceInfoLabel")
        speak_layout.addWidget(self.speak_device_info)
        speak_layout.setContentsMargins(0, 0, 0, 0)

        self.speak_device_widget.setLayout(speak_layout)
        self.speak_device_widget.hide()  # 默认隐藏
        device_layout.addWidget(self.speak_device_widget)

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
        device_name = self.get_virtual_audio_device_name()
        help_label = QLabel(f"""
        <b>📖 使用说明:</b><br>
        <b>👂 听模式</b>: 捕获会议音频（英文）→显示中文字幕（适合听英文会议）<br>
        <b>🎤 说模式</b>: 捕获中文麦克风→输出英文到虚拟麦克风（适合说中文参会）<br>
        <b>🔄 双向模式</b>: 同时运行听+说（完整双向同传）<br>
        <br>
        <b>💡 提示:</b> 说模式需要安装 {device_name} 虚拟音频设备
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

        logger.info(f"切换到模式: {self.current_mode.value}")

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
                self.config_manager.set_listen_device_name(device['name'])

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
                self.config_manager.set_speak_input_device_name(input_device['name'])
            if output_device:
                self.config_manager.set_speak_output_device_name(output_device['name'])

    def on_voice_changed(self, index):
        """语音音色选择事件"""
        voice = self.voice_combo.itemData(index)
        if voice:
            # 保存语音配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_voice(voice)

    def load_devices(self):
        """加载音频设备列表"""
        # 1. 加载听模式设备（输入设备，优先 WASAPI Loopback）
        input_devices = self.device_manager.get_input_devices()
        self.listen_device_combo.clear()

        for device in input_devices:
            display_name = device['name']
            if device.get('is_wasapi_loopback'):
                display_name += " [推荐-WASAPI]"
            elif device.get('is_loopback'):
                display_name += " [推荐]"
            self.listen_device_combo.addItem(display_name, device)

        # 自动选择推荐设备
        self._auto_select_loopback(self.listen_device_combo)

        # 2. 加载说模式输入设备（真实麦克风，排除 loopback）
        self.speak_input_combo.clear()
        for device in input_devices:
            if not device.get('is_loopback') and not device.get('is_wasapi_loopback'):
                self.speak_input_combo.addItem(device['name'], device)

        # 3. 加载说模式输出设备（虚拟麦克风，如 Voicemeeter Input 或 BlackHole）
        output_devices = self.device_manager.get_output_devices()
        self.speak_output_combo.clear()
        device_patterns = self.get_virtual_audio_device_pattern()

        for device in output_devices:
            display_name = device['name']
            # 优先推荐索引 14（测试验证可用 - Windows only）
            if device['index'] == 14 and platform.system() == "Windows":
                display_name += " [推荐-已验证]"
            elif any(pattern in device['name'] for pattern in device_patterns):
                display_name += " [推荐]"
            self.speak_output_combo.addItem(display_name, device)

        # 自动选择虚拟音频设备
        self._auto_select_virtual_device(self.speak_output_combo)

    def _auto_select_loopback(self, combo: QComboBox):
        """自动选择 Loopback 设备"""
        # 优先选择 WASAPI Loopback
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_wasapi_loopback'):
                combo.setCurrentIndex(i)
                logger.info(f"自动选择 WASAPI Loopback: {device['name']}")
                return

        # 次选传统 loopback
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_loopback'):
                combo.setCurrentIndex(i)
                logger.info(f"自动选择 Loopback: {device['name']}")
                return

    def _auto_select_virtual_device(self, combo: QComboBox):
        """自动选择虚拟音频设备（Voicemeeter/BlackHole等）"""
        device_patterns = self.get_virtual_audio_device_pattern()

        # Windows: 优先选择索引 14（测试结果显示能正常工作）
        if platform.system() == "Windows":
            for i in range(combo.count()):
                device = combo.itemData(i)
                if device['index'] == 14:
                    combo.setCurrentIndex(i)
                    logger.info(f"自动选择虚拟设备（索引 14）: {device['name']}")
                    return

        # 备选：任何匹配的虚拟音频设备
        for i in range(combo.count()):
            device = combo.itemData(i)
            if any(pattern in device['name'] for pattern in device_patterns):
                combo.setCurrentIndex(i)
                logger.info(f"自动选择虚拟设备: {device['name']}")
                return

    def _load_provider_voices(self):
        """加载当前提供商支持的声音"""
        from translation_client_factory import TranslationClientFactory

        self.voice_combo.clear()
        voices = TranslationClientFactory.get_supported_voices(self.provider)

        if not voices:
            # 如果提供商没有定义声音，使用默认值
            logger.warning(f"提供商 {self.provider} 没有定义声音，使用默认值")
            self.voice_combo.addItem("默认声音", "")
            return

        # 添加所有支持的声音
        for voice_id, voice_name in voices.items():
            self.voice_combo.addItem(voice_name, voice_id)

        # 尝试从环境变量或配置文件恢复上次选择的声音
        saved_voice = self.config_manager.get_voice()
        if saved_voice:
            for i in range(self.voice_combo.count()):
                if self.voice_combo.itemData(i) == saved_voice:
                    self.voice_combo.setCurrentIndex(i)
                    break

        logger.info(f"已加载 {self.provider} 提供商的 {len(voices)} 个声音")

    def load_config(self):
        """加载保存的配置"""
        logger.info("=" * 60)
        logger.info("开始加载上次保存的配置...")

        # 显示所有配置项（用于调试）
        logger.info(f"  模式: {self.config_manager.get_mode()}")
        logger.info(f"  听模式设备: {self.config_manager.get_listen_device_name()}")
        logger.info(f"  说模式输入: {self.config_manager.get_speak_input_device_name()}")
        logger.info(f"  说模式输出: {self.config_manager.get_speak_output_device_name()}")
        logger.info(f"  语音音色: {self.config_manager.get_voice()}")

        # 1. 恢复翻译模式
        saved_mode = self.config_manager.get_mode()
        for i in range(self.mode_combo.count()):
            mode = self.mode_combo.itemData(i)
            if mode.value == saved_mode:
                self.mode_combo.setCurrentIndex(i)
                logger.info(f"✓ 恢复模式: {saved_mode}")
                break

        # 2. 恢复听模式设备（通过名字匹配）
        # 不管当前模式，都恢复所有模式的配置
        listen_device_name = self.config_manager.get_listen_device_name()
        if listen_device_name:
            self._select_device_by_name(self.listen_device_combo, listen_device_name, "听模式设备")

        # 3. 恢复说模式输入设备
        speak_input_name = self.config_manager.get_speak_input_device_name()
        if speak_input_name:
            self._select_device_by_name(self.speak_input_combo, speak_input_name, "说模式输入设备")

        # 4. 恢复说模式输出设备
        speak_output_name = self.config_manager.get_speak_output_device_name()
        if speak_output_name:
            self._select_device_by_name(self.speak_output_combo, speak_output_name, "说模式输出设备")

        # 5. 恢复语音音色
        saved_voice = self.config_manager.get_voice()
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == saved_voice:
                self.voice_combo.setCurrentIndex(i)
                logger.info(f"✓ 恢复语音音色: {saved_voice}")
                break

        logger.info("配置加载完成")
        logger.info("=" * 60)

    def _select_device_by_name(self, combo: QComboBox, device_name: str, device_type: str):
        """通过设备名字选择设备"""
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device and device['name'] == device_name:
                combo.setCurrentIndex(i)
                logger.info(f"✓ 恢复{device_type}: {device_name}")
                return
        logger.warning(f"⚠ 未找到{device_type}: {device_name}（设备可能已变化，使用默认值）")

    def toggle_translation(self):
        """启动/停止翻译"""
        if not self.is_running:
            self.start_translation()
        else:
            self.stop_translation()

    def start_translation(self):
        """启动翻译（根据模式）"""
        logger.info(f"启动翻译（模式：{self.current_mode.value}）...")
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
            logger.error(f"启动翻译失败: {e}", exc_info=True)
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

            logger.info("翻译已启动")

        except Exception as e:
            logger.error(f"启动翻译失败: {e}")
            import traceback
            traceback.print_exc()
            self.update_status(f"启动失败: {str(e)}", "error")

            # 清理
            self.stop_translation(save_subtitles=False)

    def _start_listen_mode(self):
        """启动听模式（会议音频→中文字幕）"""
        logger.info("启动听模式...")

        # 获取设备
        device = self.listen_device_combo.currentData()
        if not device:
            raise ValueError("请先选择会议音频输入设备")

        # 1. 创建字幕窗口
        if not self.subtitle_window:
            self.subtitle_window = SubtitleWindow()
        self.subtitle_window.show()

        # 2. 启动翻译服务（英→中，仅字幕）
        self.listen_translation_service = MeetingTranslationServiceWrapper(
            api_key=self.api_key,
            on_translation=self.on_listen_translation,
            source_language="en",
            target_language="zh",
            audio_enabled=False,  # 仅字幕
            provider=self.provider,
            on_error=self.on_service_error_callback
        )
        self.listen_translation_service.start()

        # 3. 启动音频捕获（会议音频）
        device_sample_rate = device['sample_rate']
        device_channels = device['channels']

        logger.info(f"听模式设备: {device['name']}, {device_sample_rate}Hz, {device_channels}声道")

        # 根据 provider 确定目标采样率
        if self.provider == "openai":
            target_sample_rate = 24000  # OpenAI Realtime API 需要 24kHz
        else:
            target_sample_rate = 16000  # 阿里云需要 16kHz

        self.listen_audio_capture = AudioCaptureThread(
            device_index=device['index'],
            on_audio_chunk=self.listen_translation_service.send_audio_chunk,
            sample_rate=device_sample_rate,
            channels=device_channels,
            target_sample_rate=target_sample_rate,
            target_channels=1
        )
        self.listen_audio_capture.start()

        logger.info("听模式已启动")

    def _start_speak_mode(self):
        """启动说模式（中文麦克风→英文虚拟麦克风）"""
        logger.info("启动说模式...")

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
            logger.info("正在创建音频输出线程...")
            self.speak_audio_output = AudioOutputThread(
                device_index=output_device['index'],
                input_sample_rate=24000,  # API 输出 24kHz
                output_sample_rate=24000,  # 直接使用 24kHz，避免重采样问题
                channels=1,
                enable_dynamic_speed=True,  # 启用自适应变速
                max_speed=2.0,  # 最高2倍速
                queue_threshold=20,  # 队列低于20正常播放
                target_catchup_time=10.0,  # 10秒内追上进度
                max_chunks_per_batch=50  # 单次最多处理50个chunks
            )
            logger.info("音频输出线程已创建，正在启动...")
            self.speak_audio_output.start()
            logger.info("音频输出线程启动成功")
        except Exception as e:
            logger.error(f"启动音频输出线程失败: {e}", exc_info=True)
            raise

        # 2. 启动翻译服务（中→英，音频输出）
        # 获取用户选择的音色
        selected_voice = self.voice_combo.currentData()  # "Cherry" 或 "Nofish"

        try:
            logger.info("正在创建翻译服务...")
            self.speak_translation_service = MeetingTranslationServiceWrapper(
                api_key=self.api_key,
                on_translation=self.on_speak_translation,
                source_language="zh",
                target_language="en",
                audio_enabled=True,  # 启用音频
                voice=selected_voice,
                on_audio_chunk=self.speak_audio_output.write_audio_chunk,  # 写入虚拟麦克风
                provider=self.provider,
                on_error=self.on_service_error_callback
            )
            logger.info("翻译服务已创建，正在启动...")
            self.speak_translation_service.start()
            logger.info("翻译服务启动成功")
        except Exception as e:
            logger.error(f"启动翻译服务失败: {e}", exc_info=True)
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

        logger.info(f"说模式输入: {input_device['name']}, {input_sample_rate}Hz, {input_channels}声道")
        logger.info(f"说模式输出: {output_device['name']}")
        logger.info(f"英文语音音色: {selected_voice}")

        # 根据 provider 确定目标采样率
        if self.provider == "openai":
            target_sample_rate = 24000  # OpenAI Realtime API 需要 24kHz
        else:
            target_sample_rate = 16000  # 阿里云需要 16kHz

        try:
            logger.info("正在创建音频捕获线程...")
            self.speak_audio_capture = AudioCaptureThread(
                device_index=input_device['index'],
                on_audio_chunk=self.speak_translation_service.send_audio_chunk,
                sample_rate=input_sample_rate,
                channels=input_channels,
                target_sample_rate=target_sample_rate,
                target_channels=1
            )
            logger.info("音频捕获线程已创建，正在启动...")
            self.speak_audio_capture.start()
            logger.info("音频捕获线程启动成功")
        except Exception as e:
            logger.error(f"启动音频捕获失败: {e}", exc_info=True)
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

        logger.info("说模式已启动")

    def stop_translation(self, save_subtitles=True):
        """
        停止翻译

        Args:
            save_subtitles: 是否保存字幕（默认True）
        """
        logger.info("停止翻译...")

        # 1. 保存字幕（如果有内容）
        if save_subtitles and self.subtitle_window:
            try:
                save_dir = os.path.join(os.path.expanduser("~"), "Documents", "会议记录")
                os.makedirs(save_dir, exist_ok=True)

                filepath = self.subtitle_window.save_subtitles(save_dir)
                if filepath:
                    logger.info(f"✅ 字幕已保存: {filepath}")
                    self.update_status(f"已保存到: {os.path.basename(filepath)}", "ready")
            except Exception as e:
                logger.error(f"保存字幕失败: {e}")

        # 2. 停止听模式
        try:
            if self.listen_audio_capture:
                self.listen_audio_capture.stop()
                self.listen_audio_capture = None
        except Exception as e:
            logger.error(f"停止音频捕获时出错: {e}")

        try:
            if self.listen_translation_service:
                self.listen_translation_service.stop()
                self.listen_translation_service = None
        except Exception as e:
            logger.error(f"停止翻译服务时出错: {e}")

        # 3. 停止说模式
        try:
            if self.speak_audio_capture:
                self.speak_audio_capture.stop()
                self.speak_audio_capture = None
        except Exception as e:
            logger.error(f"停止说模式音频捕获时出错: {e}")

        try:
            if self.speak_translation_service:
                self.speak_translation_service.stop()
                self.speak_translation_service = None
        except Exception as e:
            logger.error(f"停止说模式翻译服务时出错: {e}")

        try:
            if self.speak_audio_output:
                self.speak_audio_output.stop()
                self.speak_audio_output = None
        except Exception as e:
            logger.error(f"停止音频输出时出错: {e}")

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
            logger.error(f"更新UI时出错: {e}")
            import traceback
            traceback.print_exc()

        logger.info("翻译已停止")
        logger.info(f"主窗口状态: visible={self.isVisible()}, enabled={self.isEnabled()}")

    def toggle_subtitle_window(self):
        """显示/隐藏字幕窗口"""
        if self.subtitle_window:
            if self.subtitle_window.isVisible():
                self.subtitle_window.hide()
                self.subtitle_btn.setText("📺 字幕窗口")
            else:
                self.subtitle_window.show()
                self.subtitle_btn.setText("🔳 隐藏字幕")

    def on_listen_translation(self, source_text: str, target_text: str, is_final: bool = True):
        """听模式翻译回调（在独立线程中调用）"""
        # 发送信号到主线程
        self.signals.translation_received.emit(source_text, target_text, is_final)

    def on_speak_translation(self, source_text: str, target_text: str, is_final: bool = True):
        """说模式翻译回调（在独立线程中调用）"""
        # 说模式只需要音频输出，文本可选记录
        if is_final:
            logger.info(f"[说模式翻译] {source_text} → {target_text}")

    def on_translation_received(self, source_text: str, target_text: str, is_final: bool = True):
        """
        翻译接收（在主线程中调用）

        Args:
            source_text: 源语言文本
            target_text: 目标语言文本
            is_final: 是否为最终文本（True=已finalize，False=增量文本）
        """
        if is_final:
            logger.info(f"翻译: {source_text} -> {target_text}")
        else:
            logger.debug(f"增量翻译: {target_text}")

        # 更新字幕窗口
        if self.subtitle_window:
            self.subtitle_window.update_subtitle(source_text, target_text, is_final=is_final)

    def on_service_error_callback(self, error_message: str, exception: Exception):
        """
        服务错误回调（在服务线程中调用）
        发送信号到主线程进行UI更新

        Args:
            error_message: 用户友好的错误消息
            exception: 原始异常对象
        """
        logger.error(f"服务错误: {error_message}")
        # 发送信号到主线程
        self.signals.error_occurred.emit(error_message, exception)

    def on_service_error(self, error_message: str, exception: Exception):
        """
        服务错误处理（在主线程中调用）
        显示错误对话框并停止翻译服务

        Args:
            error_message: 用户友好的错误消息
            exception: 原始异常对象
        """
        from PyQt5.QtWidgets import QMessageBox

        # 停止翻译服务（如果正在运行）
        if self.is_running:
            self.stop_translation()

        # 显示错误对话框
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("翻译服务错误")
        msg_box.setText(error_message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

        # 更新状态
        self.update_status("错误：服务启动失败", "error")

    def closeEvent(self, event):
        """关闭事件"""
        logger.info("主窗口关闭事件被触发")

        # 停止翻译
        self.stop_translation()

        # 关闭字幕窗口
        if self.subtitle_window:
            self.subtitle_window.close()

        # 清理设备管理器
        if self.device_manager:
            self.device_manager.cleanup()

        logger.info("主窗口即将关闭")
        event.accept()


def exception_hook(exc_type, exc_value, exc_traceback):
    """全局异常处理钩子"""
    if issubclass(exc_type, KeyboardInterrupt):
        # 让 KeyboardInterrupt 正常处理
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("未捕获的异常:", exc_info=(exc_type, exc_value, exc_traceback))


def main():
    """主函数"""
    # 安装全局异常处理钩子
    sys.excepthook = exception_hook

    try:
        app = QApplication(sys.argv)

        # 创建主窗口
        window = MeetingTranslatorApp()
        window.show()

        logger.info("进入主事件循环")
        exit_code = app.exec_()
        logger.info(f"主事件循环已退出，退出码: {exit_code}")

        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"主函数发生异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
