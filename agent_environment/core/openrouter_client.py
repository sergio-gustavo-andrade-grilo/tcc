import httpx

from agent_environment.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str = OPENROUTER_URL,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else OPENROUTER_API_KEY
        self.model = model if model is not None else OPENROUTER_MODEL
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        if not self.model:
            raise ValueError("OPENROUTER_MODEL is not set")
        self.url = url
        self._http = http or httpx.Client()

    def complete(self, prompt: str) -> str:
        response = self._http.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]