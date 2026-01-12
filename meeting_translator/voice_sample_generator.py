"""
音色样本生成器
负责生成和管理各 provider 的音色样本文件
"""

import asyncio
import json
import base64
import wave
import time
from pathlib import Path
from typing import Optional, Dict
import concurrent.futures

from paths import VOICE_SAMPLES_DIR, ASSETS_DIR
from output_manager import Out


class VoiceSampleGenerator:
    """音色样本生成器"""

    def __init__(self, provider: str, client_factory):
        """
        初始化音色样本生成器

        Args:
            provider: Provider 名称 (aliyun, openai)
            client_factory: TranslationClientFactory 实例
        """
        self.provider = provider
        self.client_factory = client_factory

    def get_audio_input_path(self) -> Path:
        """
        获取标准音频输入文件路径

        根据不同 provider 返回对应采样率的输入文件：
        - Aliyun/Qwen: 16kHz
        - OpenAI: 24kHz
        - Doubao: 16kHz
        """
        if self.provider in ["aliyun", "alibaba", "doubao"]:
            return ASSETS_DIR / "voice_sample_input_16k.wav"
        elif self.provider == "openai":
            return ASSETS_DIR / "voice_sample_input_24k.wav"
        else:
            return None

    def check_missing_voices(self, supported_voices: Dict[str, str]) -> list:
        """
        检查缺失的音色样本文件

        Args:
            supported_voices: 支持的音色字典 {voice_id: display_name}

        Returns:
            缺失的音色ID列表
        """
        provider_prefix = {
            "aliyun": "qwen",
            "alibaba": "qwen",
            "openai": "openai"
        }.get(self.provider, self.provider)

        missing = []
        for voice_id in supported_voices.keys():
            filename = f"{provider_prefix}_{voice_id}.wav"
            filepath = VOICE_SAMPLES_DIR / filename
            if not filepath.exists():
                missing.append(voice_id)

        return missing

    def generate_sample(self, voice_id: str, timeout: int = 15) -> bool:
        """
        生成单个音色样本文件

        Args:
            voice_id: 音色ID
            timeout: 超时时间（秒）

        Returns:
            bool: 是否成功生成
        """
        try:
            # 构建输出文件路径
            provider_prefix = {
                "aliyun": "qwen",
                "alibaba": "qwen",
                "openai": "openai"
            }.get(self.provider, self.provider)

            filename = f"{provider_prefix}_{voice_id}.wav"
            filepath = VOICE_SAMPLES_DIR / filename

            # 创建临时 client
            client = self.client_factory.create_client(
                provider=self.provider,
                api_key=None,  # 从环境变量加载
                voice=voice_id,
                audio_enabled=True,  # S2S 模式
                audio_queue=None  # 不需要外部队列
            )

            # 调用 client 的生成方法
            result_path = client.generate_sample_file(
                input_wav_path=str(self.get_audio_input_path()),
                output_wav_path=str(filepath)
            )

            if result_path:
                return True
            else:
                print(f"  [FAIL] {voice_id} (文件未生成)")
                return False

        except Exception as e:
            import traceback
            print(f"  [FAIL] {voice_id} (错误: {e})")
            # 打印详细错误堆栈
            traceback.print_exc()
            return False

    def generate_all_samples(self, voice_ids: list, show_progress: bool = True) -> Dict[str, bool]:
        """
        生成所有缺失的音色样本

        Args:
            voice_ids: 需要生成的音色ID列表
            show_progress: 是否显示进度

        Returns:
            字典 {voice_id: success}
        """
        results = {}

        if show_progress:
            print(f"\n正在生成 {self.provider.upper()} 音色样本文件，请稍候...")
            print(f"需要生成 {len(voice_ids)} 个音色样本")

        for voice_id in voice_ids:
            try:
                success = self.generate_sample(voice_id, timeout=15)

                if show_progress:
                    if success:
                        print(f"  [OK] {voice_id}")
                    else:
                        print(f"  [FAIL] {voice_id} (失败)")

                results[voice_id] = success

                # 等待 2 秒再生成下一个音色，避免 API 调用太快
                if voice_id != voice_ids[-1]:  # 不是最后一个
                    time.sleep(2)

            except Exception as e:
                if show_progress:
                    print(f"  [FAIL] {voice_id} (错误: {e})")
                results[voice_id] = False

                # 即使出错也等待，避免快速重试
                if voice_id != voice_ids[-1]:
                    time.sleep(2)

        if show_progress:
            success_count = sum(1 for v in results.values() if v)
            print(f"音色样本生成完成 ({success_count}/{len(voice_ids)} 成功)\n")

        return results


def generate_provider_samples(provider: str, client_factory, supported_voices: Dict[str, str]) -> Dict[str, bool]:
    """
    为指定 provider 生成所有缺失的音色样本

    Args:
        provider: Provider 名称
        client_factory: TranslationClientFactory 实例
        supported_voices: 支持的音色字典

    Returns:
        字典 {voice_id: success}
    """
    if not supported_voices:
        return {}

    generator = VoiceSampleGenerator(provider, client_factory)

    # 检查缺失的音色
    missing = generator.check_missing_voices(supported_voices)

    if not missing:
        if provider != "doubao":  # 豆包不显示
            print(f"[OK] {provider} 所有音色样本文件已齐全")
        return {}

    # 生成缺失的音色样本
    return generator.generate_all_samples(missing)
