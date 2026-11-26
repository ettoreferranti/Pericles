"""Ollama over HTTP, standard library only (REQ-LLM-002; ADR-0017 §3)."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion

Transport = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]
DETAIL = 200


def http_json(
    method: str, url: str, body: dict[str, Any] | None, timeout_s: float
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:DETAIL]
        raise BackendError(f"{method} {url}: HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise BackendError(f"{method} {url}: {error}") from None
    except UnicodeDecodeError:
        raise BackendError(f"{method} {url}: reply is not valid UTF-8") from None
    try:
        payload = json.loads(text)
    except ValueError:
        raise BackendError(f"{method} {url}: reply is not JSON: {text[:DETAIL]!r}") from None
    if not isinstance(payload, dict):
        raise BackendError(f"{method} {url}: reply is not a JSON object")
    return payload


def tagged(name: str) -> str:
    """Ollama's name for a model: no tag means `:latest`."""
    return name if ":" in name else f"{name}:latest"


class OllamaBackend:
    kind = "ollama"

    def __init__(
        self, url: str, timeout_s: float, concurrency: int, transport: Transport = http_json
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.concurrency = concurrency
        self._transport = transport

    def describe(self) -> str:
        return f"ollama at {self.url}"

    def available(self) -> list[str]:
        payload = self._transport("GET", f"{self.url}/api/tags", None, self.timeout_s)
        models = payload.get("models")
        if not isinstance(models, list) or not all(
            isinstance(m, dict) and isinstance(m.get("name"), str) for m in models
        ):
            raise LLMSetupError(f"{self.describe()}: unexpected model listing")
        return sorted(str(m["name"]) for m in models)

    def check(self, models: Sequence[str]) -> None:
        try:
            available = self.available()
        except BackendError as error:
            raise LLMSetupError(
                f"cannot reach {self.describe()} ({error}); is `ollama serve` running?"
            ) from None
        have = {tagged(name) for name in available}
        missing = [m for m in models if tagged(m) not in have]
        if missing:
            raise LLMSetupError(
                f"{self.describe()}: model(s) not available: {', '.join(missing)}. "
                f"Available: {', '.join(available) or 'none'}. "
                f"Pull with `ollama pull {missing[0]}`."
            )

    def complete(self, call: BackendCall) -> Completion:
        body: dict[str, Any] = {
            "model": call.model,
            "messages": [m.to_dict() for m in call.messages],
            "stream": False,
            "options": {
                "temperature": call.sampling.temperature,
                "top_p": call.sampling.top_p,
                "num_predict": call.sampling.max_tokens,
                "seed": call.seed,
            },
        }
        if call.schema is not None:
            body["format"] = dict(call.schema)
        payload = self._transport("POST", f"{self.url}/api/chat", body, self.timeout_s)
        message = payload.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise BackendError(f"{self.describe()}: unexpected reply {str(payload)[:DETAIL]}")
        return Completion(
            text, int(payload.get("prompt_eval_count", 0)), int(payload.get("eval_count", 0))
        )
