from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validators.library import normalize_library_name, normalize_symbol_list
from app.validators.sources import validate_source_urls


class RequestContract(BaseModel):
    library: str
    symbols: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("library")
    @classmethod
    def normalize_library(cls, value: str) -> str:
        cleaned = normalize_library_name(value)
        if not cleaned:
            raise ValueError("library is required")
        return cleaned

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("symbols must be a list")
        return normalize_symbol_list(value)


class SourceContract(BaseModel):
    library: str
    official_docs: str
    github_repo: str
    pypi_url: str
    latest_version: str

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_urls(self) -> "SourceContract":
        validate_source_urls([self.official_docs, self.github_repo, self.pypi_url])
        return self


class SymbolLifecycleContract(BaseModel):
    symbol: str
    introduced_version: str
    deprecated_version: str | None = None
    removed_version: str | None = None
    replacement_symbol: str | None = None

    model_config = ConfigDict(extra="forbid")


class ReleaseArtifactContract(BaseModel):
    version: str
    url: str
    published_at: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        validate_source_urls([value])
        return value


class MigrationGuideContract(BaseModel):
    title: str
    url: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        validate_source_urls([value])
        return value


class LibraryFactsContract(BaseModel):
    library: str
    latest_version: str
    release_history: list[ReleaseArtifactContract]
    migration_guides: list[MigrationGuideContract]

    model_config = ConfigDict(extra="forbid")


class ToolResponseContract(BaseModel):
    library: str
    latest_version: str
    official_docs: str
    github_repo: str
    pypi_url: str
    symbol_lifecycles: list[SymbolLifecycleContract]
    release_history: list[ReleaseArtifactContract]
    migration_guides: list[MigrationGuideContract]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_urls(self) -> "ToolResponseContract":
        validate_source_urls([self.official_docs, self.github_repo, self.pypi_url])
        return self


class FailureResponseContract(BaseModel):
    status: str = "failed"
    reason: str

    model_config = ConfigDict(extra="forbid")


class HealthResponseContract(BaseModel):
    status: Literal["healthy", "unhealthy"]
    mongodb: Literal["connected", "disconnected"]
    cache_expiry_days: int
    service_version: str
    uptime_seconds: int

    model_config = ConfigDict(extra="forbid")


class BulkLibraryRequestItemContract(RequestContract):
    pass


class BulkLibraryRequestContract(BaseModel):
    libraries: list[BulkLibraryRequestItemContract]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_request_size(self) -> "BulkLibraryRequestContract":
        from app.config import MAX_LIBRARIES_PER_REQUEST

        if len(self.libraries) > MAX_LIBRARIES_PER_REQUEST:
            raise ValueError("too_many_libraries")
        return self


class BulkLibraryResultContract(BaseModel):
    library: str
    status: Literal["success", "failed"]
    result: ToolResponseContract | None = None
    reason: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_status(self) -> "BulkLibraryResultContract":
        if self.status == "success" and self.result is None:
            raise ValueError("result is required for success status")
        if self.status == "failed" and self.reason is None:
            raise ValueError("reason is required for failed status")
        return self


class BulkLibraryResponseContract(BaseModel):
    results: list[BulkLibraryResultContract]

    model_config = ConfigDict(extra="forbid")


class RequestLogContract(BaseModel):
    request_id: str
    endpoint: str
    library: str | None = None
    libraries: list[str] | None = None
    symbols: list[str] | None = None
    cache_hit: bool
    response_time_ms: int
    status: str
    timestamp: datetime

    model_config = ConfigDict(extra="forbid")


class ErrorLogContract(BaseModel):
    request_id: str
    endpoint: str
    error_type: str
    error_message: str
    timestamp: datetime

    model_config = ConfigDict(extra="forbid")


class AuditLogContract(BaseModel):
    event: str
    request_id: str
    library: str | None = None
    timestamp: datetime
    details: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class ServiceMetricsContract(BaseModel):
    date: str
    requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0

    model_config = ConfigDict(extra="forbid")


class ApiKeyContract(BaseModel):
    name: str
    key_hash: str
    active: bool = True
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class SymbolIntelligenceRequestContract(BaseModel):
    library: str
    symbol: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("library")
    @classmethod
    def normalize_library(cls, value: str) -> str:
        cleaned = normalize_library_name(value)
        if not cleaned:
            raise ValueError("library is required")
        return cleaned

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("symbol is required")
        return cleaned


class SymbolIntelligenceResponseContract(SymbolLifecycleContract):
    pass
