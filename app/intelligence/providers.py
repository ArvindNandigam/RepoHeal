import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.intelligence.webtool_client import WebtoolClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
    """Intelligence provider using Groq LLM to detect deprecated APIs and replacements."""

    def __init__(self):
        from app.llm.providers import GroqProvider as GroqLLM
        from app.llm.base import LLMConfig
        cfg = LLMConfig()
        self.llm = GroqLLM(cfg)
        self._session = None

    async def get_bulk_intelligence(
        self,
        libraries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        results = []
        for entry in libraries:
            lib = entry.get("library", "")
            symbols = entry.get("symbols", [])
            try:
                result = await self._query_library(lib, symbols)
                results.append(result)
            except Exception as e:
                logger.error(f"Groq query failed for {lib}: {e}")
                results.append({
                    "library": lib,
                    "status": "failed",
                    "reason": str(e),
                    "results": [],
                })
        return {"results": results}

    async def _query_library(self, library: str, symbols: List[str]) -> Dict[str, Any]:
        batch_size = 20
        all_results = []
        latest_version = "unknown"

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            prompt = (
                f"You are a library migration expert. For the Python library '{library}', "
                f"analyze each of the following symbols/functions and determine:\n"
                f"1. Is the symbol deprecated? If so, what is the replacement?\n"
                f"2. What version was it deprecated in / removed in?\n"
                f"3. What is the latest stable version of '{library}'?\n\n"
                f"Symbols to analyze:\n" + "\n".join(f"- {s}" for s in batch) +
                "\n\nRespond ONLY with a valid JSON object in this exact format (no markdown, no code fences):\n"
                '{\n'
                f'  "library": "{library}",\n'
                '  "latest_version": "x.y.z",\n'
                '  "results": [\n'
                '    {\n'
                '      "symbol": "SymbolName",\n'
                '      "relationships": [\n'
                '        {\n'
                '          "relation": "deprecated_in_favor_of" | "replaced_by" | "removed_in" | "deprecated_in",\n'
                '          "target": "ReplacementSymbol",\n'
                '          "status": "deprecated" | "breaking" | "healthy",\n'
                '          "confidence": 0.0-1.0\n'
                '        }\n'
                '      ]\n'
                '    }\n'
                '  ]\n'
                '}\n\n'
                'If a symbol has no known deprecation, set "relationships" to an empty list [].\n'
                'Use "deprecated_in_favor_of" when the symbol is deprecated and has a direct replacement.\n'
                'Use "removed_in" when the symbol was removed entirely (breaking change).\n'
                'Use "deprecated_in" when the symbol was deprecated without a clear replacement.\n'
                'Set "confidence" based on how sure you are (0.0-1.0).'
            )

            raw = await self.llm.generate(prompt, max_tokens=4096)
            parsed = self._parse_response(raw, library)

            if "latest_version" in parsed and parsed["latest_version"] != "unknown":
                latest_version = parsed["latest_version"]
            all_results.extend(parsed.get("results", []) or [])

        return {
            "library": library,
            "status": "success",
            "latest_version": latest_version,
            "results": all_results,
        }

    def _parse_response(self, raw: str, library: str) -> Dict[str, Any]:
        json_str = raw.strip()
        json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
        json_str = re.sub(r"\s*```$", "", json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        json_match = re.search(r"\{[\s\S]*\}", json_str)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse Groq response for {library}, returning empty results")
        return {"library": library, "latest_version": "unknown", "results": []}

    async def close(self) -> None:
        await self.llm.close()


def create_intelligence_provider() -> IntelligenceProvider:
    return RestrictedWebtoolProvider()
