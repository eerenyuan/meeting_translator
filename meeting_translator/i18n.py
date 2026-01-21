"""
I18n Manager
Manages internationalization (i18n) for the Meeting Translator application
Supports multiple languages with JSON-based translation files
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path


class I18nManager:
    """
    Internationalization Manager (Singleton)

    Loads translation files and provides translation lookup methods
    Supports nested keys with dot notation (e.g., "ui.button.start")
    Falls back to Chinese (zh_CN) if translation key not found
    """

    _instance: Optional['I18nManager'] = None
    _initialized: bool = False

    def __new__(cls):
        """Singleton pattern - only one instance allowed"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the i18n manager (only once)"""
        if I18nManager._initialized:
            return

        self.current_language = "zh_CN"
        self.translations: Dict[str, Any] = {}
        self.fallback_translations: Dict[str, Any] = {}

        # Get locales directory path
        self.locales_dir = Path(__file__).parent / "locales"

        # Load default language (Chinese)
        self._load_language("zh_CN", is_fallback=True)

        I18nManager._initialized = True

    def set_language(self, language: str):
        """
        Set the current language and load translations

        Args:
            language: Language code (zh_CN, en_US, or shorthand: zh, en, cn)
        """
        # Normalize language code
        normalized_lang = self._normalize_language_code(language)

        if normalized_lang == self.current_language:
            return  # Already loaded

        # Load the new language
        if self._load_language(normalized_lang):
            self.current_language = normalized_lang
        else:
            # If loading fails, keep current language
            print(f"[I18n] Failed to load language: {normalized_lang}, keeping: {self.current_language}")

    def _normalize_language_code(self, language: str) -> str:
        """
        Normalize language code to standard format

        Supports:
        - Full codes: zh_CN, en_US, zh-CN, en-US
        - Shorthand: zh, cn → zh_CN, en → en_US

        Args:
            language: Language code (any format)

        Returns:
            Normalized language code (e.g., zh_CN, en_US)
        """
        lang_lower = language.lower().replace("-", "_")

        # Map shorthand codes to full codes
        shorthand_map = {
            "zh": "zh_CN",
            "cn": "zh_CN",
            "en": "en_US",
        }

        if lang_lower in shorthand_map:
            return shorthand_map[lang_lower]

        # If already in full format (zh_CN, en_US), return as-is
        if "_" in lang_lower:
            parts = lang_lower.split("_")
            if len(parts) == 2:
                # Capitalize country code: zh_cn → zh_CN
                return f"{parts[0]}_{parts[1].upper()}"

        # Default to Chinese if unrecognized
        return "zh_CN"

    def _load_language(self, language: str, is_fallback: bool = False) -> bool:
        """
        Load translation file for the specified language

        Args:
            language: Language code (zh_CN, en_US)
            is_fallback: Whether this is the fallback language

        Returns:
            True if loaded successfully, False otherwise
        """
        locale_file = self.locales_dir / f"{language}.json"

        if not locale_file.exists():
            print(f"[I18n] Translation file not found: {locale_file}")
            return False

        try:
            with open(locale_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)

            if is_fallback:
                self.fallback_translations = translations
            else:
                self.translations = translations

            print(f"[I18n] Loaded translations: {language} ({len(translations)} keys)")
            return True

        except json.JSONDecodeError as e:
            print(f"[I18n] JSON decode error in {locale_file}: {e}")
            return False
        except Exception as e:
            print(f"[I18n] Failed to load {locale_file}: {e}")
            return False

    def t(self, key: str, **kwargs) -> str:
        """
        Translate a key to the current language

        Supports:
        - Nested keys with dot notation: "ui.button.start"
        - Parameter substitution: t("greeting", name="Alice") → "Hello, Alice!"
        - Fallback to Chinese if key not found

        Args:
            key: Translation key (e.g., "ui.button.start")
            **kwargs: Parameters for string substitution

        Returns:
            Translated string
        """
        # Try current language first
        value = self._get_nested_value(self.translations, key)

        # Fallback to Chinese if not found
        if value is None:
            value = self._get_nested_value(self.fallback_translations, key)

        # If still not found, return the key itself as a last resort
        if value is None:
            print(f"[I18n] Translation key not found: {key}")
            return f"[{key}]"

        # Apply parameter substitution if needed
        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError as e:
                print(f"[I18n] Missing parameter in translation '{key}': {e}")
                return value

        return value

    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Optional[str]:
        """
        Get value from nested dictionary using dot notation

        Args:
            data: Dictionary to search in
            key: Dot-separated key (e.g., "ui.button.start")

        Returns:
            Value if found, None otherwise
        """
        keys = key.split(".")
        current = data

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return None

        return current if isinstance(current, str) else None

    def get_current_language(self) -> str:
        """Get the current language code"""
        return self.current_language


# Global instance (singleton)
_i18n_instance = I18nManager()


def get_i18n() -> I18nManager:
    """Get the global I18n manager instance"""
    return _i18n_instance


def t(key: str, **kwargs) -> str:
    """
    Convenience function for translation

    Args:
        key: Translation key
        **kwargs: Parameters for string substitution

    Returns:
        Translated string
    """
    return _i18n_instance.t(key, **kwargs)


# Test code
if __name__ == "__main__":
    # Test the i18n manager
    i18n = get_i18n()

    # Test Chinese (default)
    print("\n=== Testing Chinese (default) ===")
    print(f"Current language: {i18n.get_current_language()}")

    # Test English
    print("\n=== Testing English ===")
    i18n.set_language("en_US")
    print(f"Current language: {i18n.get_current_language()}")

    # Test shorthand
    print("\n=== Testing shorthand codes ===")
    i18n.set_language("cn")
    print(f"cn → {i18n.get_current_language()}")

    i18n.set_language("en")
    print(f"en → {i18n.get_current_language()}")
