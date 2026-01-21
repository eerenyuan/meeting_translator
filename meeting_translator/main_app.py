"""
会议翻译主应用
整合音频捕获、翻译服务和字幕显示
支持 S2T（字幕）和 S2S（语音翻译）独立运行
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
from PyQt5.QtGui import QBrush, QColor
from dotenv import load_dotenv


class VoicePreviewSignals(QObject):
    """音色试听信号"""
    finished = pyqtSignal()


from audio_device_manager import AudioDeviceManager
from audio_capture_thread import AudioCaptureThread
from audio_output_thread import AudioOutputThread
from translation_service import MeetingTranslationServiceWrapper
from translation_client_factory import TranslationClientFactory
from subtitle_window import SubtitleWindow
from config_manager import ConfigManager
from output_manager import Out, MessageType
from output_handlers import ConsoleHandler, LogFileHandler, AlertHandler, SubtitleHandler
from paths import LOGS_DIR, RECORDS_DIR, ensure_directories, get_initialization_message
from i18n import get_i18n

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

    # 语言名称到 i18n 键的映射（用于翻译显示名称）
    LANGUAGE_NAME_TO_KEY = {
        "中文": "chinese",
        "英语": "english",
        "西班牙语": "spanish",
        "法语": "french",
        "葡萄牙语": "portuguese",
        "俄语": "russian",
        "日语": "japanese",
        "韩语": "korean",
        "德语": "german",
        "意大利语": "italian",
        "粤语": "cantonese",
    }

    def __init__(self):
        super().__init__()

        # 初始化配置管理器（需要尽早初始化，因为i18n依赖它）
        self.config_manager = ConfigManager()

        # 初始化 i18n（从配置加载语言设置）
        self.i18n = get_i18n()
        self.i18n.set_language(self.config_manager.get_lang())

        # 获取 API Key
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
        if not self.api_key:
            Out.error(self.i18n.t("errors.api_key_not_set"))
            sys.exit(1)

        # 语言配置
        self.my_language = "中文"  # 我的语言
        self.meeting_language = "英语"  # 会议语言

        # S2T 和 S2S 独立配置
        self.s2t_provider = "aliyun"
        self.s2s_provider = "aliyun"
        self.s2s_voice = "cherry"

        # S2T 和 S2S 运行状态
        self.s2t_is_running = False
        self.s2s_is_running = False

        # 初始化设备管理器
        self.device_manager = AudioDeviceManager()

        # S2T 组件（字幕翻译）
        self.s2t_audio_capture = None
        self.s2t_translation_service = None

        # S2S 组件（语音翻译）
        self.s2s_audio_capture = None
        self.s2s_translation_service = None
        self.s2s_audio_output = None

        # 字幕窗口
        self.subtitle_window = None

        # 初始化 OutputManager
        self._init_output_manager()

        # 运行状态
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
            Out.status("\n" + "="*60)
            Out.status(init_message)
            Out.status("="*60 + "\n")

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
        # （见 _start_s2t_service 方法）

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
                Out.status(self.i18n.t("status.stylesheet_loaded"))
        except Exception as e:
            Out.warning(self.i18n.t("warnings.stylesheet_load_failed", error=str(e)))

    def _get_language_display_name(self, lang_name: str) -> str:
        """
        获取语言的翻译显示名称

        Args:
            lang_name: 语言名称（中文，如 "中文", "英语"）

        Returns:
            翻译后的显示名称（根据当前UI语言）
        """
        lang_key = self.LANGUAGE_NAME_TO_KEY.get(lang_name, lang_name.lower())
        return self.i18n.t(f"ui.languages.{lang_key}")

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle(self.i18n.t("ui.main_window.title"))
        self.setGeometry(100, 100, 700, 600)
        self.setObjectName("MainWindow")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 0. 语言选择（最顶部）
        language_group = QGroupBox(self.i18n.t("ui.groups.language_settings"))
        language_layout = QHBoxLayout()
        language_layout.setSpacing(12)

        # 我的语言
        my_lang_label = QLabel(self.i18n.t("ui.labels.my_language"))
        my_lang_label.setObjectName("subtitleLabel")
        language_layout.addWidget(my_lang_label)

        self.my_language_combo = QComboBox()
        self._populate_language_combo(self.my_language_combo)
        self.my_language_combo.currentIndexChanged.connect(self.on_my_language_changed)
        language_layout.addWidget(self.my_language_combo, 1)

        # 会议语言
        meeting_lang_label = QLabel(self.i18n.t("ui.labels.meeting_language"))
        meeting_lang_label.setObjectName("subtitleLabel")
        language_layout.addWidget(meeting_lang_label)

        self.meeting_language_combo = QComboBox()
        self._populate_language_combo(self.meeting_language_combo)
        self.meeting_language_combo.currentIndexChanged.connect(self.on_meeting_language_changed)
        language_layout.addWidget(self.meeting_language_combo, 1)

        language_group.setLayout(language_layout)
        layout.addWidget(language_group)

        # 1. 刷新设备按钮（统一在顶部）
        devices_header = QHBoxLayout()
        self.refresh_devices_btn = QPushButton(self.i18n.t("ui.buttons.refresh_devices"))
        self.refresh_devices_btn.setObjectName("secondaryButton")
        self.refresh_devices_btn.clicked.connect(self.on_refresh_devices)
        devices_header.addWidget(self.refresh_devices_btn)
        devices_header.addStretch()
        layout.addLayout(devices_header)

        # 2. S2T（字幕翻译）section
        s2t_group = QGroupBox(self.i18n.t("ui.groups.s2t"))
        s2t_layout = QVBoxLayout()
        s2t_layout.setSpacing(10)

        # S2T Provider + 启动/停止按钮
        s2t_provider_layout = QHBoxLayout()
        s2t_provider_label = QLabel(self.i18n.t("ui.labels.api_provider"))
        s2t_provider_label.setObjectName("subtitleLabel")
        s2t_provider_layout.addWidget(s2t_provider_label)

        self.s2t_provider_combo = QComboBox()
        self.s2t_provider_combo.addItem("阿里云 Qwen (Alibaba Cloud)", "aliyun")
        self.s2t_provider_combo.addItem("豆包 Doubao (ByteDance)", "doubao")
        self.s2t_provider_combo.addItem("OpenAI Realtime", "openai")
        self.s2t_provider_combo.currentIndexChanged.connect(self.on_s2t_provider_changed)
        s2t_provider_layout.addWidget(self.s2t_provider_combo, 1)

        self.s2t_start_stop_btn = QPushButton(self.i18n.t("ui.buttons.start_s2t"))
        self.s2t_start_stop_btn.clicked.connect(self.on_s2t_start_stop_clicked)
        s2t_provider_layout.addWidget(self.s2t_start_stop_btn)

        self.subtitle_btn = QPushButton(self.i18n.t("ui.buttons.subtitle_window"))
        self.subtitle_btn.setObjectName("secondaryButton")
        self.subtitle_btn.setEnabled(False)
        self.subtitle_btn.clicked.connect(self.toggle_subtitle_window)
        s2t_provider_layout.addWidget(self.subtitle_btn)

        s2t_layout.addLayout(s2t_provider_layout)

        # S2T 音频输入设备
        s2t_device_label = QLabel(self.i18n.t("ui.labels.s2t_audio_input"))
        s2t_device_label.setObjectName("subtitleLabel")
        s2t_layout.addWidget(s2t_device_label)

        self.s2t_device_combo = QComboBox()
        self.s2t_device_combo.currentIndexChanged.connect(self.on_s2t_device_selected)
        s2t_layout.addWidget(self.s2t_device_combo)

        self.s2t_device_info = QLabel(self.i18n.t("ui.labels.device_info_select"))
        self.s2t_device_info.setObjectName("deviceInfoLabel")
        s2t_layout.addWidget(self.s2t_device_info)

        s2t_group.setLayout(s2t_layout)
        layout.addWidget(s2t_group)

        # 3. S2S（语音翻译）section
        s2s_group = QGroupBox(self.i18n.t("ui.groups.s2s"))
        s2s_layout = QVBoxLayout()
        s2s_layout.setSpacing(10)

        # S2S Provider + 启动/停止按钮
        s2s_provider_layout = QHBoxLayout()
        s2s_provider_label = QLabel(self.i18n.t("ui.labels.api_provider"))
        s2s_provider_label.setObjectName("subtitleLabel")
        s2s_provider_layout.addWidget(s2s_provider_label)

        self.s2s_provider_combo = QComboBox()
        self.s2s_provider_combo.addItem("阿里云 Qwen (Alibaba Cloud)", "aliyun")
        self.s2s_provider_combo.addItem("豆包 Doubao (ByteDance)", "doubao")
        self.s2s_provider_combo.addItem("OpenAI Realtime", "openai")
        self.s2s_provider_combo.currentIndexChanged.connect(self.on_s2s_provider_changed)
        s2s_provider_layout.addWidget(self.s2s_provider_combo, 1)

        self.s2s_start_stop_btn = QPushButton(self.i18n.t("ui.buttons.start_s2s"))
        self.s2s_start_stop_btn.clicked.connect(self.on_s2s_start_stop_clicked)
        s2s_provider_layout.addWidget(self.s2s_start_stop_btn)

        s2s_layout.addLayout(s2s_provider_layout)

        # S2S 输入设备（麦克风）
        self.s2s_input_label = QLabel(self.i18n.t("ui.labels.s2s_input_mic"))
        self.s2s_input_label.setObjectName("subtitleLabel")
        s2s_layout.addWidget(self.s2s_input_label)

        self.s2s_input_combo = QComboBox()
        self.s2s_input_combo.currentIndexChanged.connect(self.on_s2s_device_selected)
        s2s_layout.addWidget(self.s2s_input_combo)

        # S2S 输出设备（虚拟麦克风）
        self.s2s_output_label = QLabel(self.i18n.t("ui.labels.s2s_output_virtual_mic"))
        self.s2s_output_label.setObjectName("subtitleLabel")
        s2s_layout.addWidget(self.s2s_output_label)

        self.s2s_output_combo = QComboBox()
        self.s2s_output_combo.currentIndexChanged.connect(self.on_s2s_device_selected)
        s2s_layout.addWidget(self.s2s_output_combo)

        # S2S 音色选择
        self.s2s_voice_label = QLabel(self.i18n.t("ui.labels.s2s_voice"))
        self.s2s_voice_label.setObjectName("subtitleLabel")
        s2s_layout.addWidget(self.s2s_voice_label)

        s2s_voice_control_layout = QHBoxLayout()
        s2s_voice_control_layout.setSpacing(8)

        self.s2s_voice_combo = QComboBox()
        self.s2s_voice_combo.currentIndexChanged.connect(self.on_s2s_voice_changed)
        s2s_voice_control_layout.addWidget(self.s2s_voice_combo)

        # 音色试听按钮
        self.voice_preview_btn = QPushButton(self.i18n.t("ui.buttons.voice_preview"))
        self.voice_preview_btn.setMinimumHeight(32)
        self.voice_preview_btn.setMinimumWidth(80)
        self.voice_preview_btn.setToolTip(self.i18n.t("ui.tooltips.voice_preview"))
        self.voice_preview_btn.setObjectName("iconButton")
        self.voice_preview_btn.clicked.connect(self.on_voice_preview_clicked)
        s2s_voice_control_layout.addWidget(self.voice_preview_btn)

        s2s_layout.addLayout(s2s_voice_control_layout)

        # 音色播放器（用于停止播放）
        self.voice_player = None
        self._voice_preview_stop_flag = False
        self._voice_preview_signals = VoicePreviewSignals()
        self._voice_preview_signals.finished.connect(self._on_voice_preview_finished)

        self.s2s_device_info = QLabel(self.i18n.t("ui.labels.device_info_select"))
        self.s2s_device_info.setObjectName("deviceInfoLabel")
        s2s_layout.addWidget(self.s2s_device_info)

        s2s_group.setLayout(s2s_layout)
        layout.addWidget(s2s_group)

        # 帮助信息
        self.help_label = QLabel(self.i18n.t("ui.help.usage_instructions"))
        self.help_label.setWordWrap(True)
        self.help_label.setObjectName("infoLabel")
        layout.addWidget(self.help_label)

        self.setLayout(layout)

    def update_status(self, text, status_type="ready"):
        """更新状态显示（已移除状态显示，此方法为兼容性保留）"""
        pass  # 状态显示已移除，按钮文字和样式已足够显示状态

    # ===== 语言设置方法 =====

    def _populate_language_combo(self, combo: QComboBox):
        """
        填充语言下拉框
        使用所有 provider 支持的语言的并集
        按流行程度排序：中文、英语始终在前两位，其他按流行程度
        """
        from translation_client_factory import TranslationClientFactory

        # 收集所有语言
        all_languages = set()
        for provider in ["aliyun", "openai", "doubao"]:
            languages = TranslationClientFactory.get_supported_languages(provider)
            all_languages.update(languages.keys())

        # 按流行程度排序
        popularity_order = [
            "中文",
            "英语",
            "西班牙语",   # 世界第二大母语使用者
            "法语",       # 国际通用语之一
            "葡萄牙语",   # 巴西、葡萄牙等
            "俄语",       # 广泛使用
            "日语",       # 经济强国
            "韩语",       # 经济强国
            "德语",       # 欧洲主要语言
            "意大利语",   # 欧洲主要语言
            "粤语",       # 中文方言
        ]

        # 过滤出实际支持的语言，保持流行度顺序
        sorted_languages = [lang for lang in popularity_order if lang in all_languages]

        # 添加任何不在流行度列表中的语言（按字母顺序）
        remaining_languages = sorted(all_languages - set(sorted_languages))
        sorted_languages.extend(remaining_languages)

        # 清空并添加（显示翻译后的名称，但数据仍使用原始键）
        combo.clear()
        for lang in sorted_languages:
            # 使用翻译后的语言名称显示，但存储原始键作为数据
            display_name = self._get_language_display_name(lang)
            combo.addItem(display_name, lang)

    def on_my_language_changed(self, index):
        """我的语言变更事件"""
        if self.is_loading_config:
            return

        # 获取存储的原始语言键（而非显示的翻译名称）
        new_language = self.my_language_combo.itemData(index)
        if not new_language or new_language == self.my_language:
            return

        # 检查是否与会议语言相同
        if new_language == self.meeting_language:
            Out.user_alert(message=self.i18n.t("ui.messages.same_language_error"), title=self.i18n.t("ui.messages.language_setting_error"))
            # 回滚到原来的语言
            for i in range(self.my_language_combo.count()):
                if self.my_language_combo.itemData(i) == self.my_language:
                    self.my_language_combo.setCurrentIndex(i)
                    return

        old_language = self.my_language
        self.my_language = new_language
        self.config_manager.set_my_language(new_language)

        # 更新可用的 providers
        self._update_available_providers()

        # 使用翻译后的名称显示状态消息
        old_display = self._get_language_display_name(old_language)
        new_display = self._get_language_display_name(new_language)
        Out.status(self.i18n.t("status.my_language_changed", old=old_display, new=new_display))

    def on_meeting_language_changed(self, index):
        """会议语言变更事件"""
        if self.is_loading_config:
            return

        # 获取存储的原始语言键（而非显示的翻译名称）
        new_language = self.meeting_language_combo.itemData(index)
        if not new_language or new_language == self.meeting_language:
            return

        # 检查是否与我的语言相同
        if new_language == self.my_language:
            Out.user_alert(message=self.i18n.t("ui.messages.same_language_error"), title=self.i18n.t("ui.messages.language_setting_error"))
            # 回滚到原来的语言
            for i in range(self.meeting_language_combo.count()):
                if self.meeting_language_combo.itemData(i) == self.meeting_language:
                    self.meeting_language_combo.setCurrentIndex(i)
                    return

        old_language = self.meeting_language
        self.meeting_language = new_language
        self.config_manager.set_meeting_language(new_language)

        # 更新可用的 providers
        self._update_available_providers()

        # 使用翻译后的名称显示状态消息
        old_display = self._get_language_display_name(old_language)
        new_display = self._get_language_display_name(new_language)
        Out.status(self.i18n.t("status.meeting_language_changed", old=old_display, new=new_display))

    def _get_language_code(self, language_name: str) -> str:
        """将语言名称转换为语言代码"""
        from translation_client_factory import TranslationClientFactory

        # 从任意 provider 获取语言映射
        for provider in ["aliyun", "openai", "doubao"]:
            languages = TranslationClientFactory.get_supported_languages(provider)
            if language_name in languages:
                return languages[language_name]

        # 默认返回中文
        return "zh"

    def _update_available_providers(self):
        """根据选择的语言更新可用的 providers"""
        from translation_client_factory import TranslationClientFactory

        my_lang_code = self._get_language_code(self.my_language)
        meeting_lang_code = self._get_language_code(self.meeting_language)

        # 获取支持该语言对的 providers
        available_providers = TranslationClientFactory.get_available_providers_for_languages(
            my_lang_code, meeting_lang_code
        )

        # 更新 S2T provider combo
        self._update_provider_combo(self.s2t_provider_combo, available_providers)

        # 更新 S2S provider combo
        self._update_provider_combo(self.s2s_provider_combo, available_providers)

        # 如果当前 provider 不在可用列表中，切换到第一个可用的
        if self.s2t_provider not in available_providers and available_providers:
            new_provider = available_providers[0]
            self.s2t_provider = new_provider
            self.config_manager.set_s2t_provider(new_provider)
            # 更新 combo 选择
            for i in range(self.s2t_provider_combo.count()):
                if self.s2t_provider_combo.itemData(i) == new_provider:
                    self.s2t_provider_combo.setCurrentIndex(i)
                    break
            Out.status(f"S2T provider 已切换到: {new_provider}")

        if self.s2s_provider not in available_providers and available_providers:
            new_provider = available_providers[0]
            self.s2s_provider = new_provider
            self.config_manager.set_s2s_provider(new_provider)
            # 更新 combo 选择
            for i in range(self.s2s_provider_combo.count()):
                if self.s2s_provider_combo.itemData(i) == new_provider:
                    self.s2s_provider_combo.setCurrentIndex(i)
                    break
            Out.status(f"S2S provider 已切换到: {new_provider}")

    def _update_provider_combo(self, combo: QComboBox, available_providers: list):
        """
        更新 provider combo 的可用状态
        不可用的选项会显示为灰色并添加"(不支持)"标签
        """
        model = combo.model()

        # Provider 的原始显示文本（不含标签）
        original_texts = {
            "aliyun": "阿里云 Qwen (Alibaba Cloud)",
            "openai": "OpenAI Realtime",
            "doubao": "豆包 Doubao (ByteDance)"
        }

        for i in range(combo.count()):
            provider = combo.itemData(i)
            if not provider:
                continue

            original_text = original_texts.get(provider, combo.itemText(i))

            if provider not in available_providers:
                # 不可用：添加标签，设置灰色，禁用
                new_text = f"{original_text} ⚠️ 不支持当前语言"
                combo.setItemText(i, new_text)

                # 禁用选项
                item = model.item(i)
                if item:
                    flags = item.flags()
                    item.setFlags(flags & ~Qt.ItemIsEnabled)
                    # 设置灰色文字
                    item.setForeground(QBrush(QColor(128, 128, 128)))

            else:
                # 可用：移除标签（如果有），启用，正常颜色
                combo.setItemText(i, original_text)

                # 启用选项
                item = model.item(i)
                if item:
                    flags = item.flags()
                    item.setFlags(flags | Qt.ItemIsEnabled)
                    # 恢复正常颜色（黑色）
                    item.setForeground(QBrush(QColor(0, 0, 0)))

    # ===== S2T 事件处理 =====

    def on_s2t_provider_changed(self, index):
        """S2T Provider 变更事件"""
        new_provider = self.s2t_provider_combo.itemData(index)
        if new_provider and new_provider != self.s2t_provider:
            # 检查依赖（针对需要特定依赖的提供商）
            if new_provider == "doubao":
                from doubao_client import DoubaoClient
                is_available, error_msg = DoubaoClient.check_dependencies()
                if not is_available:
                    Out.user_alert(message=error_msg, title=self.i18n.t("ui.messages.dependency_missing"))
                    # 回滚到原来的提供商
                    for i in range(self.s2t_provider_combo.count()):
                        if self.s2t_provider_combo.itemData(i) == self.s2t_provider:
                            self.s2t_provider_combo.setCurrentIndex(i)
                            Out.warning(f"依赖缺失，已回滚到原提供商: {self.s2t_provider}")
                            return

            # 更新 provider
            self.s2t_provider = new_provider

            # 保存配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_s2t_provider(self.s2t_provider)
                provider_name = self.s2t_provider_combo.currentText()
                Out.status(f"已切换 S2T Provider: {provider_name} ({new_provider})")

    def on_s2t_device_selected(self, index):
        """S2T 设备选择事件"""
        device = self.s2t_device_combo.itemData(index)
        if device:
            info_parts = [
                f"API: {device.get('host_api', 'Unknown')}",
                f"{self.i18n.t('ui.device.sample_rate')}: {device['sample_rate']} Hz",
                f"{self.i18n.t('ui.device.channels')}: {device['channels']}"
            ]
            if device.get('is_wasapi_loopback'):
                info_parts.append(self.i18n.t("ui.device.recommended_loopback"))
            info_text = " | ".join(info_parts)
            self.s2t_device_info.setText(info_text)

            # 保存设备配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_s2t_listen_device_display(device['display_name'])

    def on_s2t_start_stop_clicked(self):
        """S2T 启动/停止按钮点击事件"""
        if self.s2t_is_running:
            self._stop_s2t_service()
        else:
            self._start_s2t_service()

    # ===== S2S 事件处理 =====

    def on_s2s_provider_changed(self, index):
        """S2S Provider 变更事件"""
        new_provider = self.s2s_provider_combo.itemData(index)
        if new_provider and new_provider != self.s2s_provider:
            # 停止正在播放的音色样本
            self._stop_voice_preview()

            # 检查依赖
            if new_provider == "doubao":
                from doubao_client import DoubaoClient
                is_available, error_msg = DoubaoClient.check_dependencies()
                if not is_available:
                    Out.user_alert(message=error_msg, title=self.i18n.t("ui.messages.dependency_missing"))
                    # 回滚
                    for i in range(self.s2s_provider_combo.count()):
                        if self.s2s_provider_combo.itemData(i) == self.s2s_provider:
                            self.s2s_provider_combo.setCurrentIndex(i)
                            Out.warning(f"依赖缺失，已回滚到原提供商: {self.s2s_provider}")
                            return

            # 更新 provider
            self.s2s_provider = new_provider

            # 重新加载该 provider 的音色列表
            self._load_s2s_voices()

            # 保存配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_s2s_provider(self.s2s_provider)
                provider_name = self.s2s_provider_combo.currentText()
                Out.status(f"已切换 S2S Provider: {provider_name} ({new_provider})")

    def on_s2s_device_selected(self, index):
        """S2S 设备选择事件"""
        input_device = self.s2s_input_combo.currentData()
        output_device = self.s2s_output_combo.currentData()

        if input_device and output_device:
            info_parts = [
                f"{self.i18n.t('ui.device.input')}: {input_device['sample_rate']}Hz",
                f"{self.i18n.t('ui.device.output')}: {output_device['sample_rate']}Hz"
            ]
            if 'CABLE' in output_device['name'] or 'VoiceMeeter' in output_device['name']:
                info_parts.append(self.i18n.t("ui.device.virtual_device_recommended"))
            info_text = " | ".join(info_parts)
            self.s2s_device_info.setText(info_text)

        # 保存设备配置（仅在非加载期间）
        if not self.is_loading_config:
            if input_device:
                self.config_manager.set_s2s_input_device_display(input_device['display_name'])
            if output_device:
                self.config_manager.set_s2s_output_device_display(output_device['display_name'])

    def on_s2s_voice_changed(self, index):
        """S2S 音色选择事件"""
        # 停止正在播放的音色样本
        self._stop_voice_preview()

        voice = self.s2s_voice_combo.itemData(index)
        if voice is not None:  # 允许空字符串（豆包不支持音色）
            # 保存语音配置（仅在非加载期间）
            if not self.is_loading_config:
                self.config_manager.set_s2s_voice(voice)
                self.s2s_voice = voice
                Out.status(f"已保存 S2S 音色: {self.s2s_provider} -> {voice or '(默认)'}")

    def on_s2s_start_stop_clicked(self):
        """S2S 启动/停止按钮点击事件"""
        if self.s2s_is_running:
            self._stop_s2s_service()
        else:
            self._start_s2s_service()

    # ===== 音色试听 =====

    def _load_s2s_voices(self):
        """加载当前 S2S provider 支持的音色列表"""
        was_loading = self.is_loading_config
        self.is_loading_config = True

        try:
            from translation_client_factory import TranslationClientFactory

            self.s2s_voice_combo.clear()

            # 获取该 provider 支持的音色（带 i18n 翻译）
            voices = TranslationClientFactory.get_supported_voices_i18n(self.s2s_provider, self.i18n)

            if not voices:
                self.s2s_voice_combo.addItem(self.i18n.t("ui.providers.not_support_voice"), "")
                self.s2s_voice_combo.setEnabled(False)
                Out.status(f"{self.s2s_provider} 不支持音色选择")
                return

            self.s2s_voice_combo.setEnabled(True)

            for voice_id, voice_name in voices.items():
                self.s2s_voice_combo.addItem(voice_name, voice_id)

            # 恢复该 provider 的音色配置
            saved_voice = self.config_manager.get_s2s_voice()
            if saved_voice:
                for i in range(self.s2s_voice_combo.count()):
                    if self.s2s_voice_combo.itemData(i) == saved_voice:
                        self.s2s_voice_combo.setCurrentIndex(i)
                        self.s2s_voice = saved_voice
                        Out.status(f"恢复 S2S 音色: {self.s2s_provider} -> {saved_voice}")
                        break
            else:
                if self.s2s_voice_combo.count() > 0:
                    self.s2s_voice_combo.setCurrentIndex(0)
                    self.s2s_voice = self.s2s_voice_combo.itemData(0)
        finally:
            self.is_loading_config = was_loading

    def _stop_voice_preview(self):
        """停止音色样本播放"""
        if self.voice_player and self.voice_player.is_alive():
            self._voice_preview_stop_flag = True
            self.voice_player.join(timeout=1.0)
            self.voice_player = None

        self.voice_preview_btn.setText(self.i18n.t("ui.buttons.voice_preview"))
        self._voice_preview_stop_flag = False

    def on_voice_preview_clicked(self):
        """音色试听按钮点击事件"""
        if self.voice_player and self.voice_player.is_alive():
            self._stop_voice_preview()
            return

        voice = self.s2s_voice_combo.currentData()
        if not voice:
            Out.warning("当前提供商不支持音色选择")
            return

        from pathlib import Path
        from paths import VOICE_SAMPLES_DIR

        provider_prefix = {
            "aliyun": "qwen",
            "openai": "openai",
            "doubao": "doubao"
        }.get(self.s2s_provider)

        if not provider_prefix:
            Out.warning(f"提供商 {self.s2s_provider} 不支持音色试听")
            return

        filename = f"{provider_prefix}_{voice}.wav"
        filepath = VOICE_SAMPLES_DIR / filename

        if not filepath.exists():
            Out.warning(f"音色样本文件不存在: {filename}")
            return

        self.voice_preview_btn.setText(self.i18n.t("ui.buttons.voice_stop"))

        self._voice_preview_stop_flag = False
        import threading
        self.voice_player = threading.Thread(
            target=self._play_voice_sample_thread,
            args=(str(filepath),),
            daemon=True
        )
        self.voice_player.start()

    def _play_voice_sample_thread(self, filepath: str):
        """在后台线程播放音色样本"""
        try:
            import wave
            import pyaudio

            wf = wave.open(filepath, 'rb')
            p = pyaudio.PyAudio()

            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )

            chunk_size = 1024
            data = wf.readframes(chunk_size)

            while len(data) > 0 and not self._voice_preview_stop_flag:
                stream.write(data)
                data = wf.readframes(chunk_size)

            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()

            if self._voice_preview_stop_flag:
                Out.status("音色试听已停止")

        except Exception as e:
            Out.error(self.i18n.t("errors.voice_sample_play_failed", error=str(e)))
        finally:
            self._voice_preview_signals.finished.emit()
            self.voice_player = None

    def _on_voice_preview_finished(self):
        """音色试听完成槽函数"""
        self.voice_preview_btn.setText(self.i18n.t("ui.buttons.voice_preview"))

    # ===== 设备刷新 =====

    def on_refresh_devices(self):
        """刷新设备列表"""
        Out.status(self.i18n.t("status.loading_devices"))

        # 保存当前选中的设备
        current_s2t_device = self.s2t_device_combo.currentData()
        current_s2s_input_device = self.s2s_input_combo.currentData()
        current_s2s_output_device = self.s2s_output_combo.currentData()

        # 重新扫描设备
        try:
            self.device_manager.refresh()
            Out.status(self.i18n.t("status.devices_scanned"))
        except Exception as e:
            Out.error(self.i18n.t("errors.refresh_devices_failed", error=str(e)))
            return

        # 重新加载设备列表
        self.load_devices()

        # 尝试恢复之前选中的设备
        self._restore_s2t_device(current_s2t_device)
        self._restore_s2s_input_device(current_s2s_input_device)
        self._restore_s2s_output_device(current_s2s_output_device)

        Out.status(self.i18n.t("status.devices_refreshed"))

    def _restore_s2t_device(self, current_device):
        """恢复 S2T 设备选择"""
        if not current_device:
            return
        for i in range(self.s2t_device_combo.count()):
            device = self.s2t_device_combo.itemData(i)
            if device and device['display_name'] == current_device['display_name']:
                self.s2t_device_combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复 S2T 设备: {current_device['display_name']}")
                return
        Out.warning(f"⚠ 未找到之前的 S2T 设备: {current_device['display_name']}")

    def _restore_s2s_input_device(self, current_device):
        """恢复 S2S 输入设备选择"""
        if not current_device:
            return
        for i in range(self.s2s_input_combo.count()):
            device = self.s2s_input_combo.itemData(i)
            if device and device['display_name'] == current_device['display_name']:
                self.s2s_input_combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复 S2S 输入设备: {current_device['display_name']}")
                return
        Out.warning(f"⚠ 未找到之前的 S2S 输入设备: {current_device['display_name']}")

    def _restore_s2s_output_device(self, current_device):
        """恢复 S2S 输出设备选择"""
        if not current_device:
            return
        for i in range(self.s2s_output_combo.count()):
            device = self.s2s_output_combo.itemData(i)
            if device and device['display_name'] == current_device['display_name']:
                self.s2s_output_combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复 S2S 输出设备: {current_device['display_name']}")
                return
        Out.warning(f"⚠ 未找到之前的 S2S 输出设备: {current_device['display_name']}")

    # ===== 设备加载 =====

    def load_devices(self):
        """加载音频设备列表"""
        # 1. 加载 S2T 设备（会议音频输入）- 支持所有输入设备
        all_input_devices = self.device_manager.get_input_devices(include_voicemeeter=False, deduplicate=True)
        self.s2t_device_combo.clear()

        for device in all_input_devices:
            display_name = device.get('display_name', device['name'])
            # 标记 loopback 设备为推荐（用于捕获系统音频）
            if device.get('is_loopback'):
                display_name += " " + self.i18n.t("ui.device.recommended_tag")
            self.s2t_device_combo.addItem(display_name, device)

        self._auto_select_loopback(self.s2t_device_combo)

        # 2. 加载 S2S 输入设备（麦克风）
        mic_devices = self.device_manager.get_real_microphones()
        self.s2s_input_combo.clear()

        for device in mic_devices:
            display_name = device.get('display_name', device['name'])
            self.s2s_input_combo.addItem(display_name, device)

        # 3. 加载 S2S 输出设备（虚拟麦克风）
        all_output_devices = self.device_manager.get_output_devices(include_voicemeeter=True, deduplicate=True)
        self.s2s_output_combo.clear()

        for device in all_output_devices:
            display_name = device.get('display_name', device['name'])
            if device.get('is_virtual'):
                display_name += " " + self.i18n.t("ui.device.virtual_tag")

            host_api = device.get('host_api', '')
            if 'WASAPI' in host_api:
                display_name += " " + self.i18n.t("ui.device.recommended_tag")
            elif 'MME' in host_api:
                display_name += " " + self.i18n.t("ui.device.available_tag")

            self.s2s_output_combo.addItem(display_name, device)

        self._auto_select_virtual_output(self.s2s_output_combo)

    def _auto_select_loopback(self, combo: QComboBox):
        """自动选择 Loopback 设备"""
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_wasapi_loopback'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择 WASAPI Loopback: {device['name']}")
                return

        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_loopback'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择 Loopback: {device['name']}")
                return

    def _auto_select_virtual_output(self, combo: QComboBox):
        """自动选择输出设备"""
        for i in range(combo.count()):
            device = combo.itemData(i)
            host_api = device.get('host_api', '')
            if device.get('is_virtual') and 'WASAPI' in host_api:
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出 (WASAPI): {device.get('display_name', device['name'])}")
                return

        for i in range(combo.count()):
            device = combo.itemData(i)
            host_api = device.get('host_api', '')
            if device.get('is_virtual') and 'MME' in host_api:
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出 (MME): {device.get('display_name', device['name'])}")
                return

        for i in range(combo.count()):
            device = combo.itemData(i)
            if device.get('is_virtual'):
                combo.setCurrentIndex(i)
                Out.status(f"自动选择虚拟输出: {device.get('display_name', device['name'])}")
                return

        if combo.count() > 0:
            combo.setCurrentIndex(0)
            device = combo.itemData(0)
            Out.status(f"自动选择输出设备: {device.get('display_name', device['name'])}")

    # ===== 配置加载 =====

    def load_config(self):
        """加载保存的配置"""
        Out.status("=" * 60)
        Out.status(self.i18n.t("status.config_loading"))

        # 显示所有配置项（使用翻译后的语言名称）
        my_lang_key = self.config_manager.get_my_language()
        meeting_lang_key = self.config_manager.get_meeting_language()
        Out.status(f"  {self.i18n.t('ui.labels.my_language')} {self._get_language_display_name(my_lang_key)}")
        Out.status(f"  {self.i18n.t('ui.labels.meeting_language')} {self._get_language_display_name(meeting_lang_key)}")
        Out.status(f"  S2T Provider: {self.config_manager.get_s2t_provider()}")
        Out.status(f"  {self.i18n.t('ui.labels.s2t_device')}: {self.config_manager.get_s2t_listen_device_display() or self.i18n.t('ui.labels.not_set')}")
        Out.status(f"  S2S Provider: {self.config_manager.get_s2s_provider()}")
        Out.status(f"  {self.i18n.t('ui.labels.s2s_input')}: {self.config_manager.get_s2s_input_device_display() or self.i18n.t('ui.labels.not_set')}")
        Out.status(f"  {self.i18n.t('ui.labels.s2s_output')}: {self.config_manager.get_s2s_output_device_display() or self.i18n.t('ui.labels.not_set')}")
        Out.status(f"  S2S 音色: {self.config_manager.get_s2s_voice()}")

        # 0. 恢复语言设置
        saved_my_lang = self.config_manager.get_my_language()
        saved_meeting_lang = self.config_manager.get_meeting_language()

        for i in range(self.my_language_combo.count()):
            if self.my_language_combo.itemData(i) == saved_my_lang:
                self.my_language_combo.setCurrentIndex(i)
                self.my_language = saved_my_lang
                display_name = self._get_language_display_name(saved_my_lang)
                Out.status(f"✓ 恢复我的语言: {display_name}")
                break

        for i in range(self.meeting_language_combo.count()):
            if self.meeting_language_combo.itemData(i) == saved_meeting_lang:
                self.meeting_language_combo.setCurrentIndex(i)
                self.meeting_language = saved_meeting_lang
                display_name = self._get_language_display_name(saved_meeting_lang)
                Out.status(f"✓ 恢复会议语言: {display_name}")
                break

        # 更新可用的 providers（基于语言设置）
        self._update_available_providers()

        # 1. 恢复 S2T Provider
        saved_s2t_provider = self.config_manager.get_s2t_provider()
        for i in range(self.s2t_provider_combo.count()):
            provider = self.s2t_provider_combo.itemData(i)
            if provider == saved_s2t_provider:
                self.s2t_provider_combo.setCurrentIndex(i)
                self.s2t_provider = saved_s2t_provider
                Out.status(f"✓ 恢复 S2T Provider: {saved_s2t_provider}")
                break

        # 2. 恢复 S2S Provider
        saved_s2s_provider = self.config_manager.get_s2s_provider()
        for i in range(self.s2s_provider_combo.count()):
            provider = self.s2s_provider_combo.itemData(i)
            if provider == saved_s2s_provider:
                self.s2s_provider_combo.setCurrentIndex(i)
                self.s2s_provider = saved_s2s_provider
                Out.status(f"✓ 恢复 S2S Provider: {saved_s2s_provider}")
                break

        # 2.5 加载 S2S 音色列表并恢复
        self._load_s2s_voices()

        # 3. 恢复 S2T 设备
        s2t_device_display = self.config_manager.get_s2t_listen_device_display()
        if s2t_device_display:
            self._select_device_by_display(self.s2t_device_combo, s2t_device_display, "S2T 设备")

        # 4. 恢复 S2S 输入设备
        s2s_input_display = self.config_manager.get_s2s_input_device_display()
        if s2s_input_display:
            self._select_device_by_display(self.s2s_input_combo, s2s_input_display, "S2S 输入设备")

        # 5. 恢复 S2S 输出设备
        s2s_output_display = self.config_manager.get_s2s_output_device_display()
        if s2s_output_display:
            self._select_device_by_display(self.s2s_output_combo, s2s_output_display, "S2S 输出设备")

        Out.status("配置加载完成")

    def _select_device_by_display(self, combo: QComboBox, device_display: str, device_type: str):
        """通过设备显示名称选择设备"""
        for i in range(combo.count()):
            device = combo.itemData(i)
            if device and device['display_name'] == device_display:
                combo.setCurrentIndex(i)
                Out.status(f"✓ 恢复{device_type}: {device_display}")
                return
        Out.warning(f"⚠ 未找到{device_type}: {device_display}")

    def _check_and_generate_voice_samples(self):
        """检查并生成所有 provider 的缺失音色样本文件"""
        from translation_client_factory import TranslationClientFactory
        from voice_sample_generator import generate_provider_samples

        # 需要检测音色的 providers（Doubao 没有音色概念）
        providers_to_check = ["aliyun", "openai"]

        try:
            for provider in providers_to_check:
                try:
                    Out.status(f"检查 {provider} 音色样本...")

                    supported_voices = TranslationClientFactory.get_supported_voices(provider)
                    if not supported_voices:
                        Out.status(f"  [SKIP] {provider} 没有支持的音色")
                        continue

                    # 生成缺失的音色样本
                    generate_provider_samples(provider, TranslationClientFactory, supported_voices)

                except Exception as e:
                    Out.error(f" {provider} 音色样本检查失败: {e}")
                    import traceback
                    traceback.print_exc()

        except Exception as e:
            Out.error(f"检查音色样本时出错: {e}\n")
            import traceback
            traceback.print_exc()

    # ===== S2T 服务管理 =====

    def _start_s2t_service(self):
        """启动 S2T 服务（字幕翻译）"""
        Out.status(self.i18n.t("status.starting_s2t"))

        # 获取设备
        device = self.s2t_device_combo.currentData()
        if not device:
            Out.user_alert(self.i18n.t("ui.messages.select_device_first_s2t"), self.i18n.t("ui.messages.device_not_selected"))
            return

        try:
            # 1. 创建字幕窗口
            if not self.subtitle_window:
                self.subtitle_window = SubtitleWindow()
            self.subtitle_window.show()

            # 2. 添加 SubtitleHandler
            self._update_subtitle_handler()

            # 3. 启动翻译服务（会议语言→我的语言，仅字幕）
            my_lang_code = self._get_language_code(self.my_language)
            meeting_lang_code = self._get_language_code(self.meeting_language)

            self.s2t_translation_service = MeetingTranslationServiceWrapper(
                api_key=None,
                source_language=meeting_lang_code,  # 会议语言
                target_language=my_lang_code,  # 我的语言
                audio_enabled=False,
                provider=self.s2t_provider
            )
            self.s2t_translation_service.start()

            # 4. 启动音频捕获
            device_sample_rate = device['sample_rate']
            device_channels = device['channels']

            # 获取该 provider 需要的输入采样率
            target_sample_rate = TranslationClientFactory.get_input_sample_rate(self.s2t_provider)

            Out.status(f"S2T 设备: {device['name']}, {device_sample_rate}Hz, {device_channels}声道")
            Out.status(f"S2T 目标采样率: {target_sample_rate}Hz (provider={self.s2t_provider})")

            self.s2t_audio_capture = AudioCaptureThread(
                device_index=device['index'],
                on_audio_chunk=self.s2t_translation_service.send_audio_chunk,
                sample_rate=device_sample_rate,
                channels=device_channels,
                target_sample_rate=target_sample_rate,
                target_channels=1
            )
            self.s2t_audio_capture.start()

            # 5. 更新 UI
            self.s2t_is_running = True
            self.s2t_start_stop_btn.setText(self.i18n.t("ui.buttons.stop_s2t"))
            self.s2t_start_stop_btn.setObjectName("stopButton")
            self.s2t_start_stop_btn.style().unpolish(self.s2t_start_stop_btn)
            self.s2t_start_stop_btn.style().polish(self.s2t_start_stop_btn)

            self.s2t_device_combo.setEnabled(False)
            self.s2t_provider_combo.setEnabled(False)
            self.subtitle_btn.setEnabled(True)

            self.update_status("s2t_running", "running")
            Out.status(self.i18n.t("status.s2t_started"))

        except Exception as e:
            Out.error(self.i18n.t("errors.s2t_start_failed", error=str(e)), exc_info=True)
            self.update_status(f"S2T 启动失败: {str(e)}", "error")
            self._stop_s2t_service()

    def _stop_s2t_service(self):
        """停止 S2T 服务"""
        Out.status(self.i18n.t("status.stopping_s2t"))

        # 停止音频捕获
        try:
            if self.s2t_audio_capture:
                self.s2t_audio_capture.stop()
                self.s2t_audio_capture = None
        except Exception as e:
            Out.error(self.i18n.t("errors.s2t_capture_stop_failed", error=str(e)))

        # 停止翻译服务
        try:
            if self.s2t_translation_service:
                self.s2t_translation_service.stop()
                self.s2t_translation_service = None
        except Exception as e:
            Out.error(self.i18n.t("errors.s2t_service_stop_failed", error=str(e)))

        # 更新 UI
        self.s2t_is_running = False
        self.s2t_start_stop_btn.setText(self.i18n.t("ui.buttons.start_s2t"))
        self.s2t_start_stop_btn.setObjectName("")
        self.s2t_start_stop_btn.style().unpolish(self.s2t_start_stop_btn)
        self.s2t_start_stop_btn.style().polish(self.s2t_start_stop_btn)

        self.s2t_device_combo.setEnabled(True)
        self.s2t_provider_combo.setEnabled(True)
        self.subtitle_btn.setEnabled(False)

        self.update_status("ready", "ready")
        Out.status(self.i18n.t("status.s2t_stopped"))

    # ===== S2S 服务管理 =====

    def _start_s2s_service(self):
        """启动 S2S 服务（语音翻译）"""
        Out.status(self.i18n.t("status.starting_s2s"))

        # 获取设备
        input_device = self.s2s_input_combo.currentData()
        output_device = self.s2s_output_combo.currentData()

        if not input_device:
            Out.user_alert(self.i18n.t("ui.messages.select_device_first_s2s_input", language=self.my_language), self.i18n.t("ui.messages.device_not_selected"))
            return
        if not output_device:
            Out.user_alert(self.i18n.t("ui.messages.select_device_first_s2s_output", language=self.meeting_language), self.i18n.t("ui.messages.device_not_selected"))
            return

        try:
            # 1. 启动音频输出线程
            api_output_rate = self.PROVIDER_OUTPUT_RATES.get(self.s2s_provider, 24000)
            Out.status(f"S2S API 音频输出采样率: {api_output_rate} Hz (provider={self.s2s_provider})")

            self.s2s_audio_output = AudioOutputThread(
                device_index=output_device['index'],
                input_sample_rate=api_output_rate,
                output_sample_rate=output_device['sample_rate'],
                channels=output_device['channels'],
                enable_dynamic_speed=True,
                max_speed=2.0,
                queue_threshold=20,
                target_catchup_time=10.0,
                max_chunks_per_batch=50
            )
            self.s2s_audio_output.start()

            # 2. 启动翻译服务（我的语言→会议语言，音频输出）
            selected_voice = self.s2s_voice_combo.currentData()
            my_lang_code = self._get_language_code(self.my_language)
            meeting_lang_code = self._get_language_code(self.meeting_language)

            self.s2s_translation_service = MeetingTranslationServiceWrapper(
                api_key=None,
                source_language=my_lang_code,  # 我的语言
                target_language=meeting_lang_code,  # 会议语言
                audio_enabled=True,
                voice=selected_voice,
                provider=self.s2s_provider,
                on_audio_chunk=self.s2s_audio_output.write_audio_chunk
            )
            self.s2s_translation_service.start()

            # 3. 启动音频捕获
            input_sample_rate = input_device['sample_rate']
            input_channels = input_device['channels']

            # 获取该 provider 需要的输入采样率
            s2s_target_sample_rate = TranslationClientFactory.get_input_sample_rate(self.s2s_provider)

            Out.status(f"S2S 输入: {input_device['name']}, {input_sample_rate}Hz, {input_channels}声道")
            Out.status(f"S2S 输出: {output_device['name']}")
            Out.status(f"S2S 音色: {selected_voice}")
            Out.status(f"S2S 目标采样率: {s2s_target_sample_rate}Hz (provider={self.s2s_provider})")

            self.s2s_audio_capture = AudioCaptureThread(
                device_index=input_device['index'],
                on_audio_chunk=self.s2s_translation_service.send_audio_chunk,
                sample_rate=input_sample_rate,
                channels=input_channels,
                target_sample_rate=s2s_target_sample_rate,
                target_channels=1
            )
            self.s2s_audio_capture.start()

            # 4. 更新 UI
            self.s2s_is_running = True
            self.s2s_start_stop_btn.setText(self.i18n.t("ui.buttons.stop_s2s"))
            self.s2s_start_stop_btn.setObjectName("stopButton")
            self.s2s_start_stop_btn.style().unpolish(self.s2s_start_stop_btn)
            self.s2s_start_stop_btn.style().polish(self.s2s_start_stop_btn)

            self.s2s_input_combo.setEnabled(False)
            self.s2s_output_combo.setEnabled(False)
            self.s2s_voice_combo.setEnabled(False)
            self.s2s_provider_combo.setEnabled(False)

            self.update_status("s2s_running", "running")
            Out.status(self.i18n.t("status.s2s_started"))

        except Exception as e:
            Out.error(self.i18n.t("errors.s2s_start_failed", error=str(e)), exc_info=True)
            self.update_status(f"S2S 启动失败: {str(e)}", "error")
            self._stop_s2s_service()

    def _stop_s2s_service(self):
        """停止 S2S 服务"""
        Out.status(self.i18n.t("status.stopping_s2s"))

        # 停止音频捕获
        try:
            if self.s2s_audio_capture:
                self.s2s_audio_capture.stop()
                self.s2s_audio_capture = None
        except Exception as e:
            Out.error(self.i18n.t("errors.s2s_capture_stop_failed", error=str(e)))

        # 停止翻译服务
        try:
            if self.s2s_translation_service:
                self.s2s_translation_service.stop()
                self.s2s_translation_service = None
        except Exception as e:
            Out.error(self.i18n.t("errors.s2s_service_stop_failed", error=str(e)))

        # 停止音频输出
        try:
            if self.s2s_audio_output:
                self.s2s_audio_output.stop()
                self.s2s_audio_output = None
        except Exception as e:
            Out.error(self.i18n.t("errors.s2s_output_stop_failed", error=str(e)))

        # 更新 UI
        self.s2s_is_running = False
        self.s2s_start_stop_btn.setText(self.i18n.t("ui.buttons.start_s2s"))
        self.s2s_start_stop_btn.setObjectName("")
        self.s2s_start_stop_btn.style().unpolish(self.s2s_start_stop_btn)
        self.s2s_start_stop_btn.style().polish(self.s2s_start_stop_btn)

        self.s2s_input_combo.setEnabled(True)
        self.s2s_output_combo.setEnabled(True)
        self.s2s_voice_combo.setEnabled(True)
        self.s2s_provider_combo.setEnabled(True)

        self.update_status("ready", "ready")
        Out.status(self.i18n.t("status.s2s_stopped"))

    # ===== 字幕窗口 =====

    def toggle_subtitle_window(self):
        """显示/隐藏字幕窗口"""
        if self.subtitle_window:
            if self.subtitle_window.isVisible():
                self.subtitle_window.hide()
                self.subtitle_btn.setText(self.i18n.t("ui.buttons.subtitle_window"))
            else:
                self.subtitle_window.show()
                self.subtitle_btn.setText(self.i18n.t("ui.buttons.hide_subtitle"))

    # ===== 窗口关闭 =====

    def closeEvent(self, event):
        """关闭事件"""
        Out.status("主窗口关闭事件被触发")

        # 停止所有服务
        if self.s2t_is_running:
            self._stop_s2t_service()
        if self.s2s_is_running:
            self._stop_s2s_service()

        # 保存字幕（如果有内容）
        if self.subtitle_window and self.subtitle_window.subtitle_history:
            try:
                from paths import RECORDS_DIR
                filepath = self.subtitle_window.save_subtitles(RECORDS_DIR)
                if filepath:
                    Out.status(f"✅ 字幕已保存: {filepath}")
            except Exception as e:
                Out.error(self.i18n.t("errors.subtitle_save_failed", error=str(e)))

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
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    import traceback
    error_msg = f"未捕获的异常: {exc_type.__name__}"
    if exc_value is not None:
        error_msg += f": {exc_value}"
    else:
        error_msg += " (异常值为 None)"

    error_msg += "\n\n堆栈跟踪:"
    error_msg += ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    Out.error(error_msg, exc_info=True)


def main():
    """主函数"""
    sys.excepthook = exception_hook

    try:
        app = QApplication(sys.argv)
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
