"""
配置管理器
保存和加载用户配置（模式、设备选择等）
支持配置格式验证和自动修复
"""
import json
import os
import shutil
from typing import Optional, Dict, Any
from datetime import datetime

from output_manager import Out
from paths import CONFIG_DIR, ensure_directories


class ConfigManager:
    """配置管理器（支持自动验证和修复）"""

    # 配置格式版本（用于验证和迁移）
    CONFIG_VERSION = "1.0"

    # 当前版本支持的配置字段
    REQUIRED_FIELDS = ["mode", "provider"]
    OPTIONAL_FIELDS = ["voices", "listen_device_display", "speak_input_device_display", "speak_output_device_display"]
    ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径，默认为 CONFIG_DIR/config.json
        """
        # 确保目录存在
        ensure_directories()

        if config_file is None:
            config_file = os.path.join(CONFIG_DIR, "config.json")

        self.config_file = config_file
        self.config: Dict[str, Any] = self._load_and_validate_config()

    def _load_and_validate_config(self) -> Dict[str, Any]:
        """
        加载并验证配置文件
        如果配置格式不正确，备份并创建新配置
        """
        if not os.path.exists(self.config_file):
            Out.status(f"配置文件不存在: {self.config_file}")
            Out.status("将创建新的配置文件")
            return self._get_default_config()

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 验证配置格式
            if not self._validate_config(config):
                Out.warning(f"配置文件格式不正确: {self.config_file}")
                # 备份旧配置
                self._backup_config()
                # 返回默认配置
                return self._get_default_config()

            Out.status(f"已从文件加载配置: {self.config_file}")
            return config

        except json.JSONDecodeError as e:
            Out.error(f"配置文件 JSON 格式错误: {e}")
            # 备份损坏的配置
            self._backup_config()
            return self._get_default_config()

        except Exception as e:
            Out.error(f"加载配置文件失败: {e}")
            return self._get_default_config()

    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """
        验证配置格式是否正确

        Args:
            config: 配置字典

        Returns:
            True: 格式正确
            False: 格式不正确
        """
        # 检查必需字段
        for field in self.REQUIRED_FIELDS:
            if field not in config:
                Out.warning(f"配置缺少必需字段: {field}")
                return False

        # 检查 mode 字段值
        valid_modes = ["LISTEN", "SPEAK", "BIDIRECTIONAL"]
        if config.get("mode") not in valid_modes:
            Out.warning(f"配置中 mode 字段值无效: {config.get('mode')}")
            return False

        # 检查 provider 字段值
        valid_providers = ["aliyun", "doubao", "openai"]
        if config.get("provider") not in valid_providers:
            Out.warning(f"配置中 provider 字段值无效: {config.get('provider')}")
            return False

        # 检查 voices 字段（如果存在）
        if "voices" in config:
            if not isinstance(config["voices"], dict):
                Out.warning("配置中 voices 字段必须是字典")
                return False

            # 检查每个 provider 的音色是否有效
            for provider, voice in config["voices"].items():
                if provider not in valid_providers:
                    Out.warning(f"配置中包含未知的 provider: {provider}")
                    return False

        # 检查设备名称字段（如果存在，必须是字符串或 None）
        device_fields = [
            "listen_device_display",
            "speak_input_device_display",
            "speak_output_device_display"
        ]
        for field in device_fields:
            if field in config:
                value = config[field]
                if value is not None and not isinstance(value, str):
                    Out.warning(f"配置中 {field} 字段必须是字符串或 None")
                    return False

        # 验证通过
        return True

    def _backup_config(self):
        """
        备份当前配置文件
        将 config.json 重命名为 config_bk_<timestamp>.json
        """
        if not os.path.exists(self.config_file):
            return

        try:
            # 生成备份文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(
                os.path.dirname(self.config_file),
                f"config_bk_{timestamp}.json"
            )

            # 重命名当前配置文件
            shutil.move(self.config_file, backup_file)
            Out.status(f"旧配置已备份到: {backup_file}")

        except Exception as e:
            Out.error(f"备份配置文件失败: {e}")

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "mode": "LISTEN",  # LISTEN / SPEAK / BIDIRECTIONAL
            "provider": "aliyun",  # aliyun / doubao / openai
            "voices": {  # 为每个 provider 单独保存音色
                "aliyun": "cherry",
                "openai": "marin",
                "doubao": ""  # 豆包不支持音色选择
            },
            "listen_device_display": None,  # 使用 display_name（包含 host api）
            "speak_input_device_display": None,
            "speak_output_device_display": None
        }

    def save_config(self):
        """
        保存配置到文件
        如果保存失败，会记录错误但不会抛出异常
        """
        try:
            # 清理旧字段（如果存在）
            if "voice" in self.config:
                del self.config["voice"]

            # 清理旧的 device_name 字段（使用 display_name 替代）
            old_fields = ["listen_device_name", "speak_input_device_name", "speak_output_device_name"]
            for field in old_fields:
                if field in self.config:
                    del self.config[field]

            # 保存配置
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            Out.status(f"配置已保存: {self.config_file}")

        except Exception as e:
            Out.error(f"保存配置文件失败: {e}")

    # ===== 基础方法 =====

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True):
        """
        设置配置项

        Args:
            key: 配置键
            value: 配置值
            auto_save: 是否自动保存（默认 True）
        """
        self.config[key] = value
        if auto_save:
            self.save_config()

    # ===== 模式 =====

    def get_mode(self) -> str:
        """获取翻译模式"""
        return self.config.get("mode", "LISTEN")

    def set_mode(self, mode: str):
        """设置翻译模式"""
        self.config["mode"] = mode
        self.save_config()

    # ===== Provider =====

    def get_provider(self) -> str:
        """获取 API 提供商"""
        return self.config.get("provider", "aliyun")

    def set_provider(self, provider: str):
        """设置 API 提供商"""
        self.config["provider"] = provider
        self.save_config()

    # ===== 音色 =====

    def get_voice(self, provider: str = "aliyun") -> str:
        """
        获取指定提供商的语音音色

        Args:
            provider: API 提供商 (aliyun/openai/doubao)

        Returns:
            音色 ID，如果未配置则返回默认值
        """
        voices = self.config.get("voices", {})
        default_voices = {
            "aliyun": "cherry",
            "openai": "marin",
            "doubao": ""
        }
        return voices.get(provider, default_voices.get(provider, ""))

    def set_voice(self, voice: str, provider: str = "aliyun"):
        """
        设置指定提供商的语音音色

        Args:
            voice: 音色 ID
            provider: API 提供商 (aliyun/openai/doubao)
        """
        if "voices" not in self.config:
            self.config["voices"] = {}
        self.config["voices"][provider] = voice
        self.save_config()

    # ===== 设备配置（使用 display_name） =====

    def get_listen_device_display(self) -> Optional[str]:
        """获取听模式设备的显示名称（包含 host api）"""
        return self.config.get("listen_device_display")

    def set_listen_device_display(self, display_name: Optional[str]):
        """
        设置听模式设备

        Args:
            display_name: 设备显示名称（例如 "麦克风 (Windows WASAPI)"）
        """
        self.config["listen_device_display"] = display_name
        self.save_config()

    def get_speak_input_device_display(self) -> Optional[str]:
        """获取说模式输入设备的显示名称"""
        return self.config.get("speak_input_device_display")

    def set_speak_input_device_display(self, display_name: Optional[str]):
        """
        设置说模式输入设备

        Args:
            display_name: 设备显示名称（例如 "麦克风 (Windows WASAPI)"）
        """
        self.config["speak_input_device_display"] = display_name
        self.save_config()

    def get_speak_output_device_display(self) -> Optional[str]:
        """获取说模式输出设备的显示名称"""
        return self.config.get("speak_output_device_display")

    def set_speak_output_device_display(self, display_name: Optional[str]):
        """
        设置说模式输出设备

        Args:
            display_name: 设备显示名称（例如 "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"）
        """
        self.config["speak_output_device_display"] = display_name
        self.save_config()

    # ===== 兼容旧版本（使用 device_name） =====

    def get_listen_device_name(self) -> Optional[str]:
        """获取听模式设备名（兼容旧版本）"""
        display = self.get_listen_device_display()
        # 从 display_name 中提取纯名称（去除 host api）
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def get_speak_input_device_name(self) -> Optional[str]:
        """获取说模式输入设备名（兼容旧版本）"""
        display = self.get_speak_input_device_display()
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def get_speak_output_device_name(self) -> Optional[str]:
        """获取说模式输出设备名（兼容旧版本）"""
        display = self.get_speak_output_device_display()
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def set_listen_device_name(self, name: Optional[str]):
        """设置听模式设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_listen_device_display(name)

    def set_speak_input_device_name(self, name: Optional[str]):
        """设置说模式输入设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_speak_input_device_display(name)

    def set_speak_output_device_name(self, name: Optional[str]):
        """设置说模式输出设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_speak_output_device_display(name)


# 测试代码
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    # 创建配置管理器
    config = ConfigManager()

    # 打印当前配置
    print("\n当前配置:")
    print(json.dumps(config.config, indent=2, ensure_ascii=False))

    # 测试设置和获取
    print("\n测试设置和获取:")
    print(f"当前模式: {config.get_mode()}")

    config.set_mode("SPEAK")
    config.set_listen_device_display("立体声混音 (Windows WASAPI)")
    config.set_speak_input_device_display("麦克风 (Windows WASAPI)")
    config.set_speak_output_device_display("Voicemeeter Input (VB-Audio Voicemeeter VAIO)")
    config.set_voice("nofish", "aliyun")

    print(f"保存后的模式: {config.get_mode()}")
    print(f"听模式设备: {config.get_listen_device_display()}")
    print(f"说模式输入: {config.get_speak_input_device_display()}")
    print(f"说模式输出: {config.get_speak_output_device_display()}")
    print(f"阿里云音色: {config.get_voice('aliyun')}")
