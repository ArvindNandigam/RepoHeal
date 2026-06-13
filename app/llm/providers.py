import httpx
from app.llm.base import BaseLLMProvider, LLMConfig
from app.utils.logger import get_logger
from app.utils.token_bucket import groq_bucket

logger = get_logger(__name__)


class GroqProvider(BaseLLMProvider):
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.client = httpx.AsyncClient(timeout=120.0)

    def _estimate_input_tokens(self, prompt: str) -> int:
        return len(prompt) // 4

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        estimated = self._estimate_input_tokens(prompt) + (max_tokens or self.config.max_tokens)
        await groq_bucket.acquire(estimated)

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
            if not resp.is_success:
                body = resp.text[:500]
                logger.error(f"Groq API {resp.status_code} for model {self.config.model}: {body}")
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            total_tokens = usage.get("total_tokens", 0)
            if total_tokens:
                await groq_bucket.record_actual(total_tokens)
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.text[:500]
            except Exception:
                pass
            logger.error(f"Groq API call failed (key_prefix={self.config.api_key[:8] if len(self.config.api_key) >= 8 else 'empty'}): {detail or e}")
            raise RuntimeError(f"Groq API {e.response.status_code} — check LLM_API_KEY and LLM_MODEL ({self.config.model}). Response: {detail}")
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
