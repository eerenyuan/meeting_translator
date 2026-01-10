"""
音频设备管理模块
列出所有可用的音频输入/输出设备
"""

import sys
import re
from typing import List, Dict, Set

try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    # 如果没有安装 PyAudioWPatch，使用标准 PyAudio
    import pyaudio

from output_manager import Out


class AudioDeviceManager:
    """音频设备管理器"""

    # Host API 优先级
    API_PRIORITY = {
        'Windows WASAPI': 4,
        'WASAPI': 4,
        'Windows WDM-KS': 3,
        'MME': 2,
        'Windows DirectSound': 1,
        'DirectSound': 1
    }

    def __init__(self):
        self.pyaudio_instance = pyaudio.PyAudio()

    def _normalize_device_name(self, device_name: str) -> str:
        """
        规范化设备名称，用于去重比较

        处理以下情况：
        1. VB-Audio 设备名称可能被截断（如 "Voicemeeter In 3 (VB-Audio Voi"）
        2. 去除括号内容（如 "(VB-Audio Voicemeeter VAIO)"）
        """
        if not device_name:
            return ""

        # 对于 VB-Audio 设备，去除括号及内容
        if 'VB-Audio' in device_name or 'VB-AUDIO' in device_name.upper():
            # 匹配括号前的内容
            match = re.match(r'^([^(]+)', device_name)
            if match:
                normalized = match.group(1).strip()
                # 特殊处理：保留 Voicemeeter Input 等关键信息
                # 例如："Voicemeeter Input " → "Voicemeeter Input"
                return normalized.rstrip()

        return device_name.strip()

    def _get_api_priority(self, host_api: str) -> int:
        """获取 Host API 的优先级"""
        if not host_api:
            return 0
        return self.API_PRIORITY.get(host_api, 0)

    def _deduplicate_devices(self, devices: List[Dict]) -> List[Dict]:
        """
        去重设备列表，优先保留高优先级 API 的设备

        Args:
            devices: 原始设备列表

        Returns:
            去重后的设备列表
        """
        # 按规范化名称分组
        device_groups: Dict[str, List[Dict]] = {}

        for device in devices:
            normalized_name = self._normalize_device_name(device['name'])

            if normalized_name not in device_groups:
                device_groups[normalized_name] = []
            device_groups[normalized_name].append(device)

        # 每组保留最高优先级的设备
        deduplicated = []

        for group_name, group_devices in device_groups.items():
            # 按优先级排序（降序）
            sorted_devices = sorted(
                group_devices,
                key=lambda d: (
                    self._get_api_priority(d.get('host_api', '')),
                    -d.get('sample_rate', 0)  # 采样率作为次要排序
                ),
                reverse=True
            )

            # 保留第一个（最高优先级）
            best_device = sorted_devices[0]

            # 记录被去重的设备（用于调试）
            if len(sorted_devices) > 1:
                removed_apis = [d.get('host_api', 'Unknown') for d in sorted_devices[1:]]
                # Out.debug(
                #     f"设备 '{best_device['name']}' 去重: "
                #     f"保留 {best_device.get('host_api')}, "
                #     f"移除 {', '.join(removed_apis)}"
                # )

            deduplicated.append(best_device)

        return deduplicated

    def get_input_devices(self, include_voicemeeter: bool = True, deduplicate: bool = True) -> List[Dict]:
        """
        获取所有输入设备（麦克风 + WASAPI Loopback）

        Args:
            include_voicemeeter: 是否包含 Voicemeeter 设备
            deduplicate: 是否去重（默认 True）

        Returns:
            List[Dict]: 设备列表，每个设备包含 index, name, channels, sample_rate, is_loopback, host_api
        """
        devices = []
        device_count = self.pyaudio_instance.get_device_count()

        # 获取 WASAPI host API 索引
        wasapi_index = None
        try:
            wasapi_info = self.pyaudio_instance.get_host_api_info_by_type(pyaudio.paWASAPI)
            wasapi_index = wasapi_info['index']
        except Exception as e:
            Out.warning(f"WASAPI 不可用: {e}")

        for i in range(device_count):
            try:
                device_info = self.pyaudio_instance.get_device_info_by_index(i)

                # 只返回输入设备
                if device_info['maxInputChannels'] > 0:
                    device_name = device_info['name']
                    host_api_index = device_info['hostApi']

                    # 过滤 Voicemeeter 设备
                    if not include_voicemeeter and 'voicemeeter' in device_name.lower():
                        continue

                    # 优先使用 WASAPI 的 isLoopbackDevice 标记
                    is_wasapi_loopback = False
                    if wasapi_index is not None and host_api_index == wasapi_index:
                        is_wasapi_loopback = device_info.get('isLoopbackDevice', False)

                    # 如果不是 WASAPI，通过名称识别 loopback 设备
                    is_legacy_loopback = any([
                        'Stereo Mix' in device_name,           # 英文：立体声混音
                        '立体声混音' in device_name,             # 中文：立体声混音
                        'CABLE Output' in device_name,         # VB-Cable Output端
                        'VoiceMeeter' in device_name and 'Out' in device_name,  # VoiceMeeter Output
                        '主声音捕获' in device_name,             # 中文：主声音捕获驱动程序
                        'Wave Out Mix' in device_name,         # 某些声卡的混音设备
                        'What U Hear' in device_name,          # Creative 声卡
                        'Loopback' in device_name.lower(),     # 通用 loopback 关键词
                        'BlackHole' in device_name,            # macOS: BlackHole 虚拟音频设备
                        'Soundflower' in device_name,          # macOS: Soundflower 虚拟音频设备
                        'Ground Control' in device_name        # macOS: 另一个虚拟音频工具
                    ])

                    # 合并判断
                    is_loopback = is_wasapi_loopback or is_legacy_loopback

                    # 获取 host API 名称
                    host_api_name = "Unknown"
                    try:
                        host_api_info = self.pyaudio_instance.get_host_api_info_by_index(host_api_index)
                        host_api_name = host_api_info['name']
                    except:
                        pass

                    # 添加显示名称（包含 host api）
                    display_name = f"{device_name} ({host_api_name})"

                    devices.append({
                        'index': i,
                        'name': device_name,
                        'display_name': display_name,
                        'channels': device_info['maxInputChannels'],
                        'sample_rate': int(device_info['defaultSampleRate']),
                        'is_loopback': is_loopback,
                        'is_wasapi_loopback': is_wasapi_loopback,
                        'host_api': host_api_name,
                        'host_api_index': host_api_index
                    })
            except Exception as e:
                Out.debug(f"无法获取设备 {i} 的信息: {e}")
                continue

        # 去重
        if deduplicate:
            devices = self._deduplicate_devices(devices)

        return devices

    def get_output_devices(self, include_voicemeeter: bool = True, deduplicate: bool = True) -> List[Dict]:
        """
        获取所有输出设备（扬声器）

        Args:
            include_voicemeeter: 是否包含 Voicemeeter 设备
            deduplicate: 是否去重（默认 True）

        Returns:
            List[Dict]: 设备列表
        """
        devices = []
        device_count = self.pyaudio_instance.get_device_count()

        for i in range(device_count):
            try:
                device_info = self.pyaudio_instance.get_device_info_by_index(i)

                # 只返回输出设备
                if device_info['maxOutputChannels'] > 0:
                    device_name = device_info['name']

                    # 过滤 Voicemeeter 设备
                    if not include_voicemeeter and 'voicemeeter' in device_name.lower():
                        continue

                    # 获取 Host API 名称
                    host_api_name = "Unknown"
                    try:
                        host_api_info = self.pyaudio_instance.get_host_api_info_by_index(device_info['hostApi'])
                        host_api_name = host_api_info['name']
                    except:
                        pass

                    # 添加显示名称（包含 host api）
                    display_name = f"{device_name} ({host_api_name})"

                    # 判断是否为虚拟设备（Voicemeeter/VB-Cable/BlackHole 等）
                    name_lower = device_name.lower()
                    is_virtual = any([
                        'voicemeeter' in name_lower,
                        'vb-cable' in name_lower or 'vb cable' in name_lower,
                        'vb-audio' in name_lower,
                        'cable input' in name_lower,
                        'cable output' in name_lower,
                        'blackhole' in name_lower,
                        'soundflower' in name_lower,
                        'ground control' in name_lower,
                        'loopback' in name_lower  # Rogue Amoeba Loopback
                    ])

                    devices.append({
                        'index': i,
                        'name': device_name,
                        'display_name': display_name,
                        'channels': device_info['maxOutputChannels'],
                        'sample_rate': int(device_info['defaultSampleRate']),
                        'host_api': host_api_name,
                        'is_virtual': is_virtual
                    })
            except Exception as e:
                Out.debug(f"无法获取设备 {i} 的信息: {e}")
                continue

        # 去重
        if deduplicate:
            devices = self._deduplicate_devices(devices)

        return devices

    def get_default_input_device(self) -> Dict:
        """获取默认输入设备"""
        try:
            default_info = self.pyaudio_instance.get_default_input_device_info()
            return {
                'index': default_info['index'],
                'name': default_info['name'],
                'channels': default_info['maxInputChannels'],
                'sample_rate': int(default_info['defaultSampleRate'])
            }
        except Exception as e:
            Out.error(f"无法获取默认输入设备: {e}")
            return None

    def get_default_output_device(self) -> Dict:
        """获取默认输出设备"""
        try:
            default_info = self.pyaudio_instance.get_default_output_device_info()
            return {
                'index': default_info['index'],
                'name': default_info['name'],
                'channels': default_info['maxOutputChannels'],
                'sample_rate': int(default_info['defaultSampleRate'])
            }
        except Exception as e:
            Out.error(f"无法获取默认输出设备: {e}")
            return None

    def get_real_microphones(self) -> List[Dict]:
        """
        获取真实麦克风设备（用于 s2s 采集）

        过滤条件：
        - 非虚拟设备（排除 Voicemeeter）
        - 非 loopback 设备

        Returns:
            真实麦克风设备列表
        """
        all_devices = self.get_input_devices(include_voicemeeter=False, deduplicate=True)

        # 过滤掉 loopback 设备
        real_microphones = [
            device for device in all_devices
            if not device.get('is_loopback', False)
        ]

        return real_microphones

    def get_real_speakers(self) -> List[Dict]:
        """
        获取真实扬声器/loopback 设备（用于 s2t 采集）

        只返回 loopback 设备（用于捕获系统音频）

        Returns:
            真实 loopback 设备列表
        """
        all_devices = self.get_input_devices(include_voicemeeter=False, deduplicate=True)

        # 只保留 loopback 设备
        real_speakers = [
            device for device in all_devices
            if device.get('is_loopback', False)
        ]

        return real_speakers

    def get_virtual_outputs(self) -> List[Dict]:
        """
        获取虚拟输出设备（用于 s2s 输出）

        只返回 Voicemeeter 输出设备

        Returns:
            Voicemeeter 虚拟输出设备列表
        """
        all_devices = self.get_output_devices(include_voicemeeter=True, deduplicate=True)

        # 只返回虚拟设备（Voicemeeter Input, AUX Input 等）
        virtual_outputs = [
            device for device in all_devices
            if device.get('is_virtual', False)
        ]

        return virtual_outputs

    def find_device_by_name(self, name_pattern: str, is_input: bool = True) -> Dict:
        """
        根据名称模糊匹配查找设备

        Args:
            name_pattern: 设备名称关键词（如 "VoiceMeeter", "CABLE"）
            is_input: True=输入设备, False=输出设备

        Returns:
            Dict: 找到的设备信息，未找到返回 None
        """
        devices = self.get_input_devices() if is_input else self.get_output_devices()

        for device in devices:
            if name_pattern.lower() in device['name'].lower():
                Out.status(f"找到设备: {device['name']}")
                return device

        Out.warning(f"未找到包含 '{name_pattern}' 的设备")
        return None

    def print_all_devices(self):
        """打印所有设备信息（调试用）"""
        print("\n" + "="*80)
        print("音频输入设备:")
        print("="*80)
        for device in self.get_input_devices():
            mark = " [LOOPBACK]" if device.get('is_loopback') else ""
            print(f"[{device['index']}] {device.get('display_name', device['name'])}{mark}")
            print(f"    声道: {device['channels']}, 采样率: {device['sample_rate']} Hz, API: {device.get('host_api', 'N/A')}")

        print("\n" + "="*80)
        print("音频输出设备:")
        print("="*80)
        for device in self.get_output_devices():
            mark = " [VIRTUAL]" if device.get('is_virtual') else ""
            print(f"[{device['index']}] {device.get('display_name', device['name'])}{mark}")
            print(f"    声道: {device['channels']}, 采样率: {device['sample_rate']} Hz, API: {device.get('host_api', 'N/A')}")

        print("\n" + "="*80)

    def refresh(self):
        """
        刷新设备列表
        重新创建 PyAudio 实例以获取最新的设备列表。
        用于检测新连接的音频设备（如蓝牙耳机、USB 麦克风等）。
        """
        try:
            # 终止旧的 PyAudio 实例
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()

            # 创建新的 PyAudio 实例
            self.pyaudio_instance = pyaudio.PyAudio()
            Out.status("设备列表已刷新")
        except Exception as e:
            Out.error(f"刷新设备列表失败: {e}")
            raise

    def cleanup(self):
        """清理资源"""
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    manager = AudioDeviceManager()

    # 打印所有设备
    manager.print_all_devices()

    # 查找特定设备
    voicemeeter = manager.find_device_by_name("VoiceMeeter")
    if voicemeeter:
        print(f"\n找到 VoiceMeeter: {voicemeeter}")

    vb_cable = manager.find_device_by_name("CABLE Output")
    if vb_cable:
        print(f"\n找到 VB-Cable: {vb_cable}")

    manager.cleanup()
