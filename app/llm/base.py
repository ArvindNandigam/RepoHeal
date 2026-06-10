from abc import ABC, abstractmethod
from typing import Any


class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        ...

    @abstractmethod
    async def close(self):
        ...


class LLMConfig:
    def __init__(self, provider: str | None = None, model: str | None = None):
        import os
        self.provider = provider or os.getenv("LLM_PROVIDER", "groq")
        self.model = model or os.getenv("LLM_MODEL", "llama3-70b-8192")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
