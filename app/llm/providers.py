import httpx
from app.llm.base import BaseLLMProvider, LLMConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GroqProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        try:
            resp = await self.client.post(self.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            raise

    async def close(self):
        await self.client.aclose()


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        try:
            resp = await self.client.post(self.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise

    async def close(self):
        await self.client.aclose()


def create_llm_provider(config: LLMConfig | None = None) -> BaseLLMProvider:
    cfg = config or LLMConfig()
    if cfg.provider == "groq":
        return GroqProvider(cfg)
    elif cfg.provider == "openai":
        return OpenAIProvider(cfg)
    else:
        raise ValueError(f"Unknown LLM provider: {cfg.provider}")
