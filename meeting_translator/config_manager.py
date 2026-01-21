"""
配置管理器
保存和加载用户配置（S2T/S2S 设备、Provider 等）
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
    CONFIG_VERSION = "2.1"

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
        如果配置版本不匹配或格式不正确，备份并创建新配置
        """
        if not os.path.exists(self.config_file):
            Out.status(f"配置文件不存在: {self.config_file}")
            Out.status("将创建新的配置文件")
            return self._get_default_config()

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 检查版本并进行迁移
            current_version = config.get('version')
            if current_version != self.CONFIG_VERSION:
                # 尝试从 2.0 迁移到 2.1
                if current_version == "2.0":
                    Out.status(f"检测到配置版本 2.0，正在迁移到 2.1...")
                    config = self._migrate_v20_to_v21(config)
                    # 保存迁移后的配置
                    self.config = config
                    self.save_config()
                    Out.status("配置迁移完成")
                else:
                    Out.warning(f"配置版本不匹配 (当前: {current_version}, 期望: {self.CONFIG_VERSION})")
                    # 备份旧配置
                    self._backup_config()
                    # 返回默认配置
                    return self._get_default_config()

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
        # 检查 lang 字段（可选，v2.1+）
        if "lang" in config:
            lang = config["lang"]
            if not isinstance(lang, str):
                Out.warning("配置中 lang 字段必须是字符串")
                return False

        # 检查 s2t 部分
        if "s2t" in config:
            s2t = config["s2t"]
            if not isinstance(s2t, dict):
                Out.warning("配置中 s2t 字段必须是字典")
                return False

            # 检查 s2t.provider
            if "provider" in s2t:
                valid_providers = ["aliyun", "doubao", "openai"]
                if s2t["provider"] not in valid_providers:
                    Out.warning(f"配置中 s2t.provider 值无效: {s2t['provider']}")
                    return False

            # 检查 s2t.listen_device_display
            if "listen_device_display" in s2t:
                value = s2t["listen_device_display"]
                if value is not None and not isinstance(value, str):
                    Out.warning("配置中 s2t.listen_device_display 必须是字符串或 None")
                    return False

        # 检查 s2s 部分
        if "s2s" in config:
            s2s = config["s2s"]
            if not isinstance(s2s, dict):
                Out.warning("配置中 s2s 字段必须是字典")
                return False

            # 检查 s2s.provider
            if "provider" in s2s:
                valid_providers = ["aliyun", "doubao", "openai"]
                if s2s["provider"] not in valid_providers:
                    Out.warning(f"配置中 s2s.provider 值无效: {s2s['provider']}")
                    return False

            # 检查 s2s.voice
            if "voice" in s2s:
                if not isinstance(s2s["voice"], str):
                    Out.warning("配置中 s2s.voice 必须是字符串")
                    return False

            # 检查 s2s 设备字段
            device_fields = ["speak_input_device_display", "speak_output_device_display"]
            for field in device_fields:
                if field in s2s:
                    value = s2s[field]
                    if value is not None and not isinstance(value, str):
                        Out.warning(f"配置中 s2s.{field} 必须是字符串或 None")
                        return False

        # 验证通过
        return True

    def _backup_config(self):
        """
        备份当前配置文件
        将 config.json 重命名为 config.json.bak
        """
        if not os.path.exists(self.config_file):
            return

        try:
            # 生成备份文件名（使用 .bak 后缀）
            backup_file = f"{self.config_file}.bak"

            # 重命名当前配置文件
            shutil.move(self.config_file, backup_file)
            Out.status(f"旧配置已备份到: {backup_file}")

        except Exception as e:
            Out.error(f"备份配置文件失败: {e}")

    def _migrate_v20_to_v21(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        从配置版本 2.0 迁移到 2.1

        Changes:
        - 添加 lang 字段（默认 zh_CN）
        - 更新版本号到 2.1

        Args:
            config: v2.0 格式的配置

        Returns:
            v2.1 格式的配置
        """
        # 添加 lang 字段（默认为中文）
        config["lang"] = "zh_CN"

        # 更新版本号
        config["version"] = "2.1"

        Out.status("配置已从 v2.0 迁移到 v2.1（添加语言设置）")
        return config

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置（v2.1 格式）"""
        return {
            "version": "2.1",
            "lang": "zh_CN",
            "my_language": "中文",
            "meeting_language": "英语",
            "s2t": {
                "provider": "aliyun",
                "listen_device_display": None
            },
            "s2s": {
                "provider": "aliyun",
                "voice": "cherry",
                "speak_input_device_display": None,
                "speak_output_device_display": None
            }
        }

    def save_config(self):
        """
        保存配置到文件
        如果保存失败，会记录错误但不会抛出异常
        """
        try:
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

    # ===== 语言配置 =====

    def get_lang(self) -> str:
        """
        获取界面语言设置

        Returns:
            语言代码 (zh_CN, en_US)
        """
        return self.config.get("lang", "zh_CN")

    def set_lang(self, lang: str):
        """
        设置界面语言

        支持多种格式:
        - 完整代码: zh_CN, en_US, zh-CN, en-US
        - 简写: zh, cn → zh_CN, en → en_US

        Args:
            lang: 语言代码
        """
        # 规范化语言代码
        normalized_lang = self._normalize_language_code(lang)

        self.config["lang"] = normalized_lang
        self.save_config()

    def _normalize_language_code(self, lang: str) -> str:
        """
        规范化语言代码

        Args:
            lang: 语言代码（任意格式）

        Returns:
            规范化后的语言代码 (zh_CN, en_US)
        """
        lang_lower = lang.lower().replace("-", "_")

        # 简写映射
        shorthand_map = {
            "zh": "zh_CN",
            "cn": "zh_CN",
            "en": "en_US",
        }

        if lang_lower in shorthand_map:
            return shorthand_map[lang_lower]

        # 如果已经是完整格式 (zh_CN, en_US)，返回原样
        if "_" in lang_lower:
            parts = lang_lower.split("_")
            if len(parts) == 2:
                # 大写国家代码: zh_cn → zh_CN
                return f"{parts[0]}_{parts[1].upper()}"

        # 默认返回中文
        return "zh_CN"

    def get_my_language(self) -> str:
        """获取我的语言"""
        return self.config.get("my_language", "中文")

    def set_my_language(self, language: str):
        """
        设置我的语言

        Args:
            language: 语言名称（例如 "中文"、"英语"）
        """
        self.config["my_language"] = language
        self.save_config()

    def get_meeting_language(self) -> str:
        """获取会议语言"""
        return self.config.get("meeting_language", "英语")

    def set_meeting_language(self, language: str):
        """
        设置会议语言

        Args:
            language: 语言名称（例如 "中文"、"英语"）
        """
        self.config["meeting_language"] = language
        self.save_config()

    # ===== S2T 配置 =====

    def get_s2t_provider(self) -> str:
        """获取 S2T Provider"""
        return self.config.get("s2t", {}).get("provider", "aliyun")

    def set_s2t_provider(self, provider: str):
        """
        设置 S2T Provider

        Args:
            provider: API 提供商 (aliyun/doubao/openai)
        """
        if "s2t" not in self.config:
            self.config["s2t"] = {}
        self.config["s2t"]["provider"] = provider
        self.save_config()

    def get_s2t_listen_device_display(self) -> Optional[str]:
        """获取 S2T 音频输入设备的显示名称"""
        return self.config.get("s2t", {}).get("listen_device_display")

    def set_s2t_listen_device_display(self, display_name: Optional[str]):
        """
        设置 S2T 音频输入设备

        Args:
            display_name: 设备显示名称（例如 "立体声混音 (Windows WASAPI)"）
        """
        if "s2t" not in self.config:
            self.config["s2t"] = {}
        self.config["s2t"]["listen_device_display"] = display_name
        self.save_config()

    # ===== S2S 配置 =====

    def get_s2s_provider(self) -> str:
        """获取 S2S Provider"""
        return self.config.get("s2s", {}).get("provider", "aliyun")

    def set_s2s_provider(self, provider: str):
        """
        设置 S2S Provider

        Args:
            provider: API 提供商 (aliyun/doubao/openai)
        """
        if "s2s" not in self.config:
            self.config["s2s"] = {}
        self.config["s2s"]["provider"] = provider
        self.save_config()

    def get_s2s_voice(self) -> str:
        """获取 S2S 音色"""
        return self.config.get("s2s", {}).get("voice", "cherry")

    def set_s2s_voice(self, voice: str):
        """
        设置 S2S 音色

        Args:
            voice: 音色 ID
        """
        if "s2s" not in self.config:
            self.config["s2s"] = {}
        self.config["s2s"]["voice"] = voice
        self.save_config()

    def get_s2s_input_device_display(self) -> Optional[str]:
        """获取 S2S 输入设备（麦克风）的显示名称"""
        return self.config.get("s2s", {}).get("speak_input_device_display")

    def set_s2s_input_device_display(self, display_name: Optional[str]):
        """
        设置 S2S 输入设备（麦克风）

        Args:
            display_name: 设备显示名称（例如 "麦克风 (Windows WASAPI)"）
        """
        if "s2s" not in self.config:
            self.config["s2s"] = {}
        self.config["s2s"]["speak_input_device_display"] = display_name
        self.save_config()

    def get_s2s_output_device_display(self) -> Optional[str]:
        """获取 S2S 输出设备（虚拟麦克风）的显示名称"""
        return self.config.get("s2s", {}).get("speak_output_device_display")

    def set_s2s_output_device_display(self, display_name: Optional[str]):
        """
        设置 S2S 输出设备（虚拟麦克风）

        Args:
            display_name: 设备显示名称（例如 "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"）
        """
        if "s2s" not in self.config:
            self.config["s2s"] = {}
        self.config["s2s"]["speak_output_device_display"] = display_name
        self.save_config()

    # ===== 兼容旧版本（v1.0） =====
    # 这些方法保留用于向后兼容，内部映射到新的 S2T/S2S 结构

    def get_mode(self) -> str:
        """获取翻译模式（兼容 v1.0，返回 "both"）"""
        return "both"

    def set_mode(self, mode: str):
        """设置翻译模式（兼容 v1.0，空操作）"""
        pass

    def get_provider(self) -> str:
        """获取 API 提供商（兼容 v1.0，返回 S2T provider）"""
        return self.get_s2t_provider()

    def set_provider(self, provider: str):
        """设置 API 提供商（兼容 v1.0，同时设置 S2T 和 S2S）"""
        self.set_s2t_provider(provider)
        self.set_s2s_provider(provider)

    def get_voice(self, provider: str = "aliyun") -> str:
        """获取音色（兼容 v1.0）"""
        return self.get_s2s_voice()

    def set_voice(self, voice: str, provider: str = "aliyun"):
        """设置音色（兼容 v1.0）"""
        self.set_s2s_voice(voice)

    def get_listen_device_display(self) -> Optional[str]:
        """获取听模式设备（兼容 v1.0）"""
        return self.get_s2t_listen_device_display()

    def set_listen_device_display(self, display_name: Optional[str]):
        """设置听模式设备（兼容 v1.0）"""
        self.set_s2t_listen_device_display(display_name)

    def get_speak_input_device_display(self) -> Optional[str]:
        """获取说模式输入设备（兼容 v1.0）"""
        return self.get_s2s_input_device_display()

    def set_speak_input_device_display(self, display_name: Optional[str]):
        """设置说模式输入设备（兼容 v1.0）"""
        self.set_s2s_input_device_display(display_name)

    def get_speak_output_device_display(self) -> Optional[str]:
        """获取说模式输出设备（兼容 v1.0）"""
        return self.get_s2s_output_device_display()

    def set_speak_output_device_display(self, display_name: Optional[str]):
        """设置说模式输出设备（兼容 v1.0）"""
        self.set_s2s_output_device_display(display_name)

    # ===== 兼容旧版本（使用 device_name） =====

    def get_listen_device_name(self) -> Optional[str]:
        """获取听模式设备名（兼容旧版本）"""
        display = self.get_s2t_listen_device_display()
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def get_speak_input_device_name(self) -> Optional[str]:
        """获取说模式输入设备名（兼容旧版本）"""
        display = self.get_s2s_input_device_display()
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def get_speak_output_device_name(self) -> Optional[str]:
        """获取说模式输出设备名（兼容旧版本）"""
        display = self.get_s2s_output_device_display()
        if display:
            import re
            match = re.match(r'^([^(]+)', display)
            if match:
                return match.group(1).strip()
        return display

    def set_listen_device_name(self, name: Optional[str]):
        """设置听模式设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_s2t_listen_device_display(name)

    def set_speak_input_device_name(self, name: Optional[str]):
        """设置说模式输入设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_s2s_input_device_display(name)

    def set_speak_output_device_name(self, name: Optional[str]):
        """设置说模式输出设备名（兼容旧版本，自动转换为 display_name）"""
        self.set_s2s_output_device_display(name)


# 测试代码
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    # 创建配置管理器
    config = ConfigManager()

    # 打印当前配置
    print("\n当前配置:")
    print(json.dumps(config.config, indent=2, ensure_ascii=False))

    # 测试 S2T 设置和获取
    print("\n测试 S2T 设置和获取:")
    config.set_s2t_provider("doubao")
    config.set_s2t_listen_device_display("立体声混音 (Windows WASAPI)")
    print(f"S2T Provider: {config.get_s2t_provider()}")
    print(f"S2T 设备: {config.get_s2t_listen_device_display()}")

    # 测试 S2S 设置和获取
    print("\n测试 S2S 设置和获取:")
    config.set_s2s_provider("openai")
    config.set_s2s_voice("marin")
    config.set_s2s_input_device_display("麦克风 (Windows WASAPI)")
    config.set_s2s_output_device_display("Voicemeeter Input (VB-Audio Voicemeeter VAIO)")
    print(f"S2S Provider: {config.get_s2s_provider()}")
    print(f"S2S 音色: {config.get_s2s_voice()}")
    print(f"S2S 输入: {config.get_s2s_input_device_display()}")
    print(f"S2S 输出: {config.get_s2s_output_device_display()}")

    # 测试兼容方法
    print("\n测试兼容旧版本方法:")
    print(f"get_provider(): {config.get_provider()}")
    print(f"get_voice(): {config.get_voice()}")
    print(f"get_listen_device_display(): {config.get_listen_device_display()}")
