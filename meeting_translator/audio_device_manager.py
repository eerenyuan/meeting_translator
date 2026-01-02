"""
音频设备管理模块
列出所有可用的音频输入/输出设备
"""

try:
    # 优先使用 PyAudioWPatch (支持 WASAPI Loopback)
    import pyaudiowpatch as pyaudio
except ImportError:
    # 如果没有安装 PyAudioWPatch，使用标准 PyAudio
    import pyaudio

import logging
import platform
from typing import List, Dict

logger = logging.getLogger(__name__)


class AudioDeviceManager:
    """音频设备管理器"""

    def __init__(self):
        self.pyaudio_instance = pyaudio.PyAudio()

    def get_input_devices(self) -> List[Dict]:
        """
        获取所有输入设备（麦克风 + WASAPI Loopback）

        Returns:
            List[Dict]: 设备列表，每个设备包含 index, name, channels, sample_rate, is_loopback, host_api
        """
        devices = []
        device_count = self.pyaudio_instance.get_device_count()

        # 获取 WASAPI host API 索引 (仅在 Windows 上)
        wasapi_index = None
        if platform.system() == "Windows":
            try:
                wasapi_info = self.pyaudio_instance.get_host_api_info_by_type(pyaudio.paWASAPI)
                wasapi_index = wasapi_info['index']
            except Exception as e:
                logger.warning(f"WASAPI 不可用: {e}")

        for i in range(device_count):
            try:
                device_info = self.pyaudio_instance.get_device_info_by_index(i)

                # 只返回输入设备
                if device_info['maxInputChannels'] > 0:
                    device_name = device_info['name']
                    host_api_index = device_info['hostApi']

                    # 优先使用 WASAPI 的 isLoopbackDevice 标记
                    is_wasapi_loopback = False
                    if wasapi_index is not None and host_api_index == wasapi_index:
                        is_wasapi_loopback = device_info.get('isLoopbackDevice', False)

                    # 如果不是 WASAPI，通过名称识别 loopback 设备
                    is_legacy_loopback = any([
                        'Stereo Mix' in device_name,           # 英文：立体声混音
                        '立体声混音' in device_name,             # 中文：立体声混音
                        'CABLE Output' in device_name,         # 虚拟音频设备 Output端
                        'VoiceMeeter' in device_name and 'Out' in device_name,  # VoiceMeeter Output
                        '主声音捕获' in device_name,             # 中文：主声音捕获驱动程序
                        'Wave Out Mix' in device_name,         # 某些声卡的混音设备
                        'What U Hear' in device_name,          # Creative 声卡
                        'Loopback' in device_name.lower()      # 通用 loopback 关键词
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

                    devices.append({
                        'index': i,
                        'name': device_name,
                        'channels': device_info['maxInputChannels'],
                        'sample_rate': int(device_info['defaultSampleRate']),
                        'is_loopback': is_loopback,
                        'is_wasapi_loopback': is_wasapi_loopback,
                        'host_api': host_api_name,
                        'host_api_index': host_api_index
                    })
            except Exception as e:
                logger.debug(f"无法获取设备 {i} 的信息: {e}")
                continue

        return devices

    def get_output_devices(self) -> List[Dict]:
        """
        获取所有输出设备（扬声器）

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
                    devices.append({
                        'index': i,
                        'name': device_info['name'],
                        'channels': device_info['maxOutputChannels'],
                        'sample_rate': int(device_info['defaultSampleRate']),
                        'is_virtual': 'CABLE Input' in device_info['name'] or
                                    'VoiceMeeter' in device_info['name']
                    })
            except Exception as e:
                logger.debug(f"无法获取设备 {i} 的信息: {e}")
                continue

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
            logger.error(f"无法获取默认输入设备: {e}")
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
            logger.error(f"无法获取默认输出设备: {e}")
            return None

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
                logger.info(f"找到设备: {device['name']}")
                return device

        logger.warning(f"未找到包含 '{name_pattern}' 的设备")
        return None

    def print_all_devices(self):
        """打印所有设备信息（调试用）"""
        print("\n" + "="*80)
        print("音频输入设备:")
        print("="*80)
        for device in self.get_input_devices():
            mark = " [LOOPBACK]" if device.get('is_loopback') else ""
            print(f"[{device['index']}] {device['name']}{mark}")
            print(f"    声道: {device['channels']}, 采样率: {device['sample_rate']} Hz")

        print("\n" + "="*80)
        print("音频输出设备:")
        print("="*80)
        for device in self.get_output_devices():
            mark = " [VIRTUAL]" if device.get('is_virtual') else ""
            print(f"[{device['index']}] {device['name']}{mark}")
            print(f"    声道: {device['channels']}, 采样率: {device['sample_rate']} Hz")

        print("\n" + "="*80)

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

    cable_output = manager.find_device_by_name("CABLE Output")
    if cable_output:
        print(f"\n找到虚拟音频设备: {cable_output}")

    manager.cleanup()
