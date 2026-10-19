import httpx
import pytest

from agent_environment.core.openrouter_client import OpenRouterClient


def test_complete_sends_prompt_and_returns_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    client = OpenRouterClient(
        api_key="test-key",
        model="some/model",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.complete("hi there") == "hello"
    assert seen["auth"] == "Bearer test-key"
    assert "hi there" in seen["body"]
    assert "some/model" in seen["body"]


def test_missing_key_raises():
    with pytest.raises(ValueError):
        OpenRouterClient(api_key="", model="some/model")