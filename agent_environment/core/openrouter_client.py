import time
from dataclasses import dataclass

import httpx

from agent_environment.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL


@dataclass(frozen=True)
class CallStats:
    model: str | None
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str = OPENROUTER_URL,
        http: httpx.Client | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else OPENROUTER_API_KEY
        self.model = model if model is not None else OPENROUTER_MODEL
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        if not self.model:
            raise ValueError("OPENROUTER_MODEL is not set")
        self.url = url
        self.temperature = temperature
        self._http = http or httpx.Client()
        self.last_stats: CallStats | None = None

    def complete(self, prompt: str) -> str:
        start = time.perf_counter()
        response = self._http.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        latency = time.perf_counter() - start
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        self.last_stats = CallStats(
            model=data.get("model"),
            latency_seconds=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return data["choices"][0]["message"]["content"]