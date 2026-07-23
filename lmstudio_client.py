from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from time import perf_counter


class LmStudioError(RuntimeError):
    pass


class LmStudioCancelled(LmStudioError):
    pass


@dataclass
class LmStudioResponse:
    text: str
    elapsed_seconds: float
    raw: dict


@dataclass
class LmStudioModelContext:
    model: str
    context_length: int
    max_context_length: int | None
    source: str
    models_url: str


def lmstudio_native_models_url(chat_completions_url: str) -> str:
    parsed = urllib.parse.urlparse(chat_completions_url)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or "localhost:1234"
    return urllib.parse.urlunparse((scheme, netloc, "/api/v1/models", "", "", ""))


def extract_lmstudio_model_context(raw: dict, preferred_model: str = "") -> LmStudioModelContext | None:
    models = raw.get("models") if isinstance(raw, dict) else None
    if models is None:
        models = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(models, list):
        return None

    preferred = str(preferred_model or "").strip()

    def model_identifiers(model: dict) -> set[str]:
        values = {
            str(model.get("key") or ""),
            str(model.get("id") or ""),
            str(model.get("display_name") or ""),
            str(model.get("selected_variant") or ""),
        }
        return {value for value in values if value}

    loaded_models = [
        model for model in models
        if isinstance(model, dict) and isinstance(model.get("loaded_instances"), list) and model.get("loaded_instances")
    ]
    candidates = loaded_models or [model for model in models if isinstance(model, dict)]
    if not candidates:
        return None

    chosen = None
    if preferred and preferred != "local-model":
        chosen = next((model for model in candidates if preferred in model_identifiers(model)), None)
    if chosen is None and len(loaded_models) == 1:
        chosen = loaded_models[0]
    if chosen is None:
        chosen = candidates[0]

    loaded_instances = chosen.get("loaded_instances") if isinstance(chosen.get("loaded_instances"), list) else []
    context_length = None
    if loaded_instances:
        config = loaded_instances[0].get("config") if isinstance(loaded_instances[0], dict) else {}
        if isinstance(config, dict):
            context_length = config.get("context_length")

    source = "loaded_instance.config.context_length"
    if context_length is None:
        context_length = chosen.get("context_length") or chosen.get("max_context_length")
        source = "model.max_context_length"

    try:
        context_length_int = int(context_length)
    except (TypeError, ValueError):
        return None

    max_context_length = chosen.get("max_context_length")
    try:
        max_context_length_int = int(max_context_length) if max_context_length is not None else None
    except (TypeError, ValueError):
        max_context_length_int = None

    model_name = (
        str(chosen.get("key") or "")
        or str(chosen.get("id") or "")
        or str(chosen.get("display_name") or "")
        or preferred
        or "local-model"
    )
    return LmStudioModelContext(
        model=model_name,
        context_length=context_length_int,
        max_context_length=max_context_length_int,
        source=source,
        models_url="",
    )


def fetch_lmstudio_model_context(
    chat_completions_url: str,
    *,
    model: str = "",
    timeout_seconds: int = 5,
) -> LmStudioModelContext | None:
    models_url = lmstudio_native_models_url(chat_completions_url)
    request = urllib.request.Request(models_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
        raw = json.loads(raw_text)
    except Exception as exc:
        raise LmStudioError(f"Contexte LM Studio indisponible: {exc}") from exc

    context = extract_lmstudio_model_context(raw, preferred_model=model)
    if context is None:
        return None
    context.models_url = models_url
    return context


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

    def chat(
        self,
        user_prompt: str,
        *,
        stop_event=None,
        response_format: dict | None = None,
        on_progress=None,
    ) -> LmStudioResponse:
        if stop_event is not None and stop_event.is_set():
            raise LmStudioCancelled("Appel LM Studio annulé avant envoi.")

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
        if stop_event is not None:
            payload["stream"] = True
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
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in content_type:
                    return self._read_streamed_response(response, started, stop_event, on_progress)
                raw_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LmStudioError(f"Erreur HTTP LM Studio {exc.code}: {details[:500]}") from exc
        except urllib.error.URLError as exc:
            raise LmStudioError(f"LM Studio injoignable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LmStudioError("Timeout LM Studio.") from exc

        if stop_event is not None and stop_event.is_set():
            raise LmStudioCancelled("Appel LM Studio annulé.")

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LmStudioError(f"Réponse LM Studio non JSON: {raw_text[:500]}") from exc

        text = self._extract_text(raw)
        if not text:
            raise LmStudioError("Réponse LM Studio vide.")

        return LmStudioResponse(text=text, elapsed_seconds=perf_counter() - started, raw=raw)

    def _read_streamed_response(self, response, started: float, stop_event, on_progress) -> LmStudioResponse:
        chunks: list[str] = []
        streamed_events: list[dict] = []
        while True:
            if stop_event is not None and stop_event.is_set():
                try:
                    response.close()
                finally:
                    raise LmStudioCancelled("Appel LM Studio annulé pendant la génération.")
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            streamed_events.append(event)
            delta = self._extract_stream_delta(event)
            if delta:
                chunks.append(delta)
                if on_progress is not None:
                    try:
                        on_progress(perf_counter() - started, len("".join(chunks)))
                    except Exception:
                        pass

        if stop_event is not None and stop_event.is_set():
            raise LmStudioCancelled("Appel LM Studio annulé.")
        text = "".join(chunks).strip()
        if not text:
            raise LmStudioError("Réponse LM Studio vide.")
        raw = {
            "choices": [{"message": {"content": text}}],
            "streamed": True,
            "event_count": len(streamed_events),
        }
        return LmStudioResponse(text=text, elapsed_seconds=perf_counter() - started, raw=raw)

    @staticmethod
    def _extract_stream_delta(raw: dict) -> str:
        choices = raw.get("choices") if isinstance(raw, dict) else None
        if not choices:
            return ""
        first = choices[0] or {}
        delta = first.get("delta") or {}
        if isinstance(delta, dict) and delta.get("content") is not None:
            return str(delta.get("content") or "")
        message = first.get("message") or {}
        if isinstance(message, dict) and message.get("content") is not None:
            return str(message.get("content") or "")
        return str(first.get("text") or "")

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
