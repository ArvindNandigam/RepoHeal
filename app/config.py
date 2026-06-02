from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass

from dotenv import load_dotenv


SERVICE_VERSION = "4.0.0"
MAX_SYMBOLS_PER_REQUEST = 50
DEFAULT_ALLOWED_DOMAINS = (
    "pypi.org",
    "github.com",
    "githubusercontent.com",
    "numpy.org",
    "pandas.pydata.org",
    "scikit-learn.org",
    "readthedocs.io",
    "readthedocs.com",
    "docs.*",
)
MAX_LIBRARIES_PER_REQUEST = 25


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_database: str = "repoheal"
    cache_expiry_days: int = 7
    port: int = 8000
    upstream_timeout_seconds: float = 15.0
    upstream_retry_count: int = 3
    internal_api_key: str | None = None
    allowed_domains: tuple[str, ...] = DEFAULT_ALLOWED_DOMAINS
    service_version: str = SERVICE_VERSION
    
    # RepoHeal V3 Settings
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    max_search_results: int = 20
    serper_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        mongodb_uri = os.getenv("MONGODB_URI", "").strip()
        if not mongodb_uri:
            raise ValueError("MONGODB_URI is required")

        mongodb_database = os.getenv("MONGODB_DATABASE", "repoheal").strip() or "repoheal"
        cache_expiry_days = int(os.getenv("CACHE_EXPIRY_DAYS", "7"))
        port = int(os.getenv("PORT", "8000"))
        upstream_timeout_seconds = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "15"))
        upstream_retry_count = int(os.getenv("UPSTREAM_RETRY_COUNT", "3"))
        internal_api_key = os.getenv("INTERNAL_API_KEY", "").strip() or None
        allowed_domains_env = os.getenv("ALLOWED_DOMAINS", "").strip()
        allowed_domains = tuple(
            domain.strip().lower()
            for domain in (allowed_domains_env.split(",") if allowed_domains_env else DEFAULT_ALLOWED_DOMAINS)
            if domain.strip()
        )
        
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip() or None
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        max_search_results = int(os.getenv("MAX_SEARCH_RESULTS", "20"))
        serper_api_key = os.getenv("SERPER_API_KEY", "").strip() or None

        return cls(
            mongodb_uri=mongodb_uri,
            mongodb_database=mongodb_database,
            cache_expiry_days=cache_expiry_days,
            port=port,
            upstream_timeout_seconds=upstream_timeout_seconds,
            upstream_retry_count=upstream_retry_count,
            internal_api_key=internal_api_key,
            allowed_domains=allowed_domains,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            max_search_results=max_search_results,
            serper_api_key=serper_api_key,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings.from_env()

