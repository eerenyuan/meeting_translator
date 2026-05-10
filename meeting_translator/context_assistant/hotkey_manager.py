import logging

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self):
        self._hotkeys = {}
        self._enabled = False
        self._keyboard = None

    def _ensure_keyboard(self):
        if self._keyboard is not None:
            return True
        try:
            import keyboard
            self._keyboard = keyboard
            return True
        except ImportError:
            logger.warning("keyboard package not installed. Hotkeys disabled. Install with: pip install keyboard")
            return False

    def register(self, key: str, callback):
        self._hotkeys[key] = callback

    def enable(self):
        if not self._ensure_keyboard():
            return
        if self._enabled:
            return
        for key, callback in self._hotkeys.items():
            try:
                self._keyboard.add_hotkey(key, callback, suppress=False)
            except Exception as e:
                logger.error(f"Failed to register hotkey {key}: {e}")
        self._enabled = True
        logger.info("Context assistant hotkeys enabled")

    def disable(self):
        if not self._enabled or self._keyboard is None:
            return
        for key in self._hotkeys:
            try:
                self._keyboard.remove_hotkey(key)
            except Exception:
                pass
        self._enabled = False
        logger.info("Context assistant hotkeys disabled")

    @property
    def is_available(self) -> bool:
        return self._keyboard is not None
