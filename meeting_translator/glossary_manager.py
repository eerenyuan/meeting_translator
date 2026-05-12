"""
术语表管理器
支持多语言术语映射，根据翻译方向自动构建词汇表

内部格式（list of dicts）：
  translations: [
    {"zh": "宇信科技", "en": "Yusys Technology", "ja": "宇信科技"},
    {"zh": "信贷系统", "en": "Loan Management System"}
  ]

每条术语是一个语言→术语的映射，翻译时根据 source/target 语言自动提取。
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from paths import CONFIG_DIR, ensure_directories


class GlossaryManager:

    def __init__(self, glossary_file: str = None):
        if glossary_file is None:
            ensure_directories()
            glossary_file = CONFIG_DIR / "glossary.json"

        self.glossary_file = Path(glossary_file)
        self.terms: List[Dict[str, str]] = self._load_glossary()

    def _load_glossary(self) -> List[Dict[str, str]]:
        if os.path.exists(self.glossary_file):
            try:
                with open(self.glossary_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                raw = data.get("translations", [])
                if isinstance(raw, list):
                    return [t for t in raw if isinstance(t, dict) and len(t) >= 2]
                if isinstance(raw, dict):
                    return self._migrate_legacy_format(raw)
            except Exception as e:
                print(f"加载术语表失败: {e}")
        return self._get_default_glossary()

    def _migrate_legacy_format(self, old: Dict[str, str]) -> List[Dict[str, str]]:
        result = []
        for key, value in old.items():
            key_is_zh = any('\u4e00' <= c <= '\u9fff' for c in key)
            val_is_zh = any('\u4e00' <= c <= '\u9fff' for c in value)
            if key_is_zh and not val_is_zh:
                result.append({"zh": key, "en": value})
            elif not key_is_zh and val_is_zh:
                result.append({"en": key, "zh": value})
            else:
                result.append({"zh": key, "en": value})
        return result

    def _get_default_glossary(self) -> List[Dict[str, str]]:
        return [
            {"zh": "人工智能", "en": "Artificial Intelligence"},
            {"zh": "机器学习", "en": "Machine Learning"},
            {"zh": "深度学习", "en": "Deep Learning"},
            {"zh": "自然语言处理", "en": "Natural Language Processing"},
            {"zh": "语音识别", "en": "Speech Recognition"},
            {"zh": "同声传译", "en": "Simultaneous Interpretation"},
        ]

    def build_for_direction(self, source_lang: str, target_lang: str) -> Dict[str, str]:
        """
        根据翻译方向构建 {源术语: 目标术语} 字典

        Args:
            source_lang: 源语言代码 (e.g., "zh", "en")
            target_lang: 目标语言代码 (e.g., "en", "ja")

        Returns:
            Dict mapping source terms to target terms
        """
        result = {}
        for term in self.terms:
            src_text = term.get(source_lang)
            tgt_text = term.get(target_lang)
            if src_text and tgt_text and src_text != tgt_text:
                result[src_text] = tgt_text
        return result

    def apply(self, text: str, source_lang: str, target_lang: str) -> str:
        glossary = self.build_for_direction(source_lang, target_lang)
        if not glossary:
            return text
        result = text
        for wrong, correct in glossary.items():
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            result = pattern.sub(correct, result)
        return result

    def save_glossary(self):
        data = {
            "translations": self.terms,
            "description": "Translation glossary for meeting translator"
        }
        try:
            with open(self.glossary_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存术语表失败: {e}")

    def add_term(self, term: Dict[str, str]):
        if len(term) >= 2:
            self.terms.append(term)
            self.save_glossary()

    def remove_term(self, index: int):
        if 0 <= index < len(self.terms):
            del self.terms[index]
            self.save_glossary()


if __name__ == "__main__":
    manager = GlossaryManager()
    print(f"Loaded {len(manager.terms)} terms")
    for t in manager.terms:
        print(f"  {t}")

    print(f"\nzh→en: {manager.build_for_direction('zh', 'en')}")
    print(f"en→zh: {manager.build_for_direction('en', 'zh')}")
    print(f"zh→ja: {manager.build_for_direction('zh', 'ja')}")

    test = "我们公司的人工智能技术很厉害"
    print(f"\nApply zh→en: '{test}' → '{manager.apply(test, 'zh', 'en')}'")
