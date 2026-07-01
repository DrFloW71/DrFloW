from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import perf_counter


class LmStudioError(RuntimeError):
    pass


@dataclass
class LmStudioResponse:
    text: str
    elapsed_seconds: float
    raw: dict


class LmStudioClient:
    def __init__(
        self,
        url: str,
        *,
        model: str = "local-model",
        temperature: float = 0.2,
        timeout_seconds: int = 120,
        system_prompt: str = "Tu es un assistant médical local.",
        max_tokens: int | None = None,
    ):
        self.url = url
        self.model = model or "local-model"
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.system_prompt = system_prompt
        self.max_tokens = int(max_tokens) if max_tokens else None

    def chat(self, user_prompt: str, *, stop_event=None, response_format: dict | None = None) -> LmStudioResponse:
        if stop_event is not None and stop_event.is_set():
            raise LmStudioError("Appel LM Studio annulé avant envoi.")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if response_format:
            payload["response_format"] = response_format
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        started = perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LmStudioError(f"Erreur HTTP LM Studio {exc.code}: {details[:500]}") from exc
        except urllib.error.URLError as exc:
            raise LmStudioError(f"LM Studio injoignable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LmStudioError("Timeout LM Studio.") from exc

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LmStudioError(f"Réponse LM Studio non JSON: {raw_text[:500]}") from exc

        text = self._extract_text(raw)
        if not text:
            raise LmStudioError("Réponse LM Studio vide.")

        return LmStudioResponse(text=text, elapsed_seconds=perf_counter() - started, raw=raw)

    @staticmethod
    def _extract_text(raw: dict) -> str:
        choices = raw.get("choices") if isinstance(raw, dict) else None
        if not choices:
            return ""
        first = choices[0] or {}
        message = first.get("message") or {}
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"]).strip()
        if first.get("text"):
            return str(first["text"]).strip()
        return ""
