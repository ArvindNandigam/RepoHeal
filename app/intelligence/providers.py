import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.intelligence.webtool_client import WebtoolClient


class IntelligenceProvider(ABC):
    """Stable interface for migration intelligence providers."""

    @abstractmethod
    async def get_bulk_intelligence(
        self,
        libraries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_symbol_intelligence(
        self,
        library: str,
        symbols: List[str]
    ) -> Dict[str, Any]:
        return await self.get_bulk_intelligence([
            {"library": library, "symbols": symbols}
        ])

    async def close(self) -> None:
        return None


class RestrictedWebtoolProvider(IntelligenceProvider):
    """Authoritative dependency, deprecation, version, and compatibility provider."""

    def __init__(self, client: WebtoolClient | None = None):
        self.client = client or WebtoolClient()

    async def get_bulk_intelligence(
        self,
        libraries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return await self.client.get_bulk_intelligence(libraries)

    async def get_symbol_intelligence(
        self,
        library: str,
        symbols: List[str]
    ) -> Dict[str, Any]:
        return await self.client.get_symbol_intelligence(library, symbols)

    async def close(self) -> None:
        await self.client.close()


class GroqProvider(IntelligenceProvider):
    """Future enrichment-only provider; not authoritative for dependency facts."""

    async def get_bulk_intelligence(
        self,
        libraries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "GroqProvider may only enrich explanations and recommendations; "
            "Restricted Webtool remains authoritative for library intelligence."
        )


def create_intelligence_provider() -> IntelligenceProvider:
    provider = os.getenv("INTELLIGENCE_PROVIDER", "restricted_webtool").lower()
    if provider in {"restricted_webtool", "webtool"}:
        return RestrictedWebtoolProvider()
    if provider == "groq":
        return GroqProvider()
    raise ValueError(f"Unsupported INTELLIGENCE_PROVIDER: {provider}")
