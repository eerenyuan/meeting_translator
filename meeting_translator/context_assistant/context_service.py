import os
import json
import logging
from typing import Optional, Callable, List, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class ContextService:
    def __init__(self, get_history_fn: Callable, on_result_fn: Callable):
        self.get_history = get_history_fn
        self.on_result = on_result_fn

        self._api_key = None
        self._api_base = None
        self._model = None
        self._init_llm_config()

    def _init_llm_config(self):
        if os.getenv("OPENAI_API_KEY"):
            self._api_key = os.getenv("OPENAI_API_KEY")
            self._api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
            self._model = os.getenv("CONTEXT_LLM_MODEL", "gpt-4o-mini")
        elif os.getenv("DASHSCOPE_API_KEY"):
            self._api_key = os.getenv("DASHSCOPE_API_KEY")
            self._api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            self._model = "qwen-plus"
        else:
            logger.warning("No API key found for Context Assistant")

    @property
    def is_available(self) -> bool:
        return self._api_key is not None

    def build_context(self, max_items: int = 8) -> str:
        history = self.get_history(max_items)
        print(f"[ContextAssistant] history count: {len(history)}")
        if history:
            print(f"[ContextAssistant] last item: {history[-1].get('target', '')[:50]}")
        if not history:
            return ""
        lines = []
        for item in history:
            ts = item.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%H:%M:%S")
            source = item.get("source", "")
            target = item.get("target", "")
            if source and target:
                lines.append(f"[{ts}] {source} → {target}")
            elif target:
                lines.append(f"[{ts}] {target}")
        return "\n".join(lines)

    def trigger(self, mode: str):
        if not self.is_available:
            self.on_result(mode, None, "API key not configured. Set OPENAI_API_KEY or DASHSCOPE_API_KEY in .env")
            return

        context = self.build_context()
        if not context:
            self.on_result(mode, None, "No subtitle history available. Start S2T first.")
            return

        try:
            from prompt_templates import get_prompt_template
        except ImportError:
            from .prompt_templates import get_prompt_template

        system_prompt = get_prompt_template(mode)

        user_content = f"Here is the recent meeting conversation:\n\n{context}\n\nBased on the conversation above, provide your assistance."
        if mode == "explain":
            user_content += "\n\nFocus on explaining key concepts, terms, or references mentioned that the user might not be familiar with."
        elif mode == "experience":
            kb_text = self._load_knowledge_base()
            if kb_text:
                user_content += f"\n\nHere is the user's knowledge base for reference:\n---\n{kb_text}\n---\n\nFind relevant experiences from the knowledge base that relate to the current topic."
            else:
                user_content += "\n\n(No knowledge base found. Answer based on general knowledge.)"
        elif mode == "ammo":
            user_content += "\n\nAnalyze the other party's claims and provide counter-arguments or supporting evidence."
        elif mode == "reply":
            user_content += "\n\nBased on the conversation flow, suggest how the user could respond."

        self._call_llm_async(mode, system_prompt, user_content)

    def _load_knowledge_base(self) -> str:
        kb_dir = Path.home() / "Documents" / "meeting_translator" / "knowledge"
        if not kb_dir.exists():
            return ""

        chunks = []
        for md_file in sorted(kb_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                header = f"=== {md_file.stem} ==="
                chunks.append(f"{header}\n{text}")
            except Exception as e:
                logger.warning(f"Failed to load knowledge file {md_file}: {e}")

        return "\n\n".join(chunks)

    def _call_llm_async(self, mode: str, system_prompt: str, user_content: str):
        import threading

        def _worker():
            try:
                result = self._call_llm(system_prompt, user_content)
                self.on_result(mode, result, None)
            except Exception as e:
                logger.error(f"Context LLM call failed: {e}")
                self.on_result(mode, None, str(e))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _call_llm(self, system_prompt: str, user_content: str) -> str:
        try:
            import urllib.request
            import urllib.error
        except ImportError:
            raise RuntimeError("urllib not available")

        url = f"{self._api_base}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.7,
            "max_tokens": 800,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._api_key}")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}")
