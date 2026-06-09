from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class HealthScoreSnapshot(BaseModel):
    repository: str
    analysis_id: str
    health_score: int
    risk_level: str
    critical_findings: int
    deprecated_count: int
    breaking_count: int
    dependency_count: int
    dependency_freshness: float = 0.0
    security_count: int = 0
    recorded_at: str


class WatchlistEntry(BaseModel):
    repository: str
    package_name: str
    installed_version: str
    latest_version: str
    risk_level: Literal["low", "medium", "high", "critical"]
    monitored_since: str
    last_checked: str
    release_notes_url: Optional[str] = None
    security_advisories: List[str] = Field(default_factory=list)
    auto_upgrade: bool = False


class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    SECURITY = "security"
    BREAKING = "breaking"
    DEPRECATION = "deprecation"
    HEALTH_DEGRADATION = "health_degradation"
    UPGRADE_AVAILABLE = "upgrade_available"
    MIGRATION_READY = "migration_ready"


class Alert(BaseModel):
    id: str
    repository: str
    category: AlertCategory
    severity: AlertSeverity
    title: str
    description: str
    package_name: Optional[str] = None
    symbol: Optional[str] = None
    affected_files: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    created_at: str
    read: bool = False
    dismissed: bool = False
    snoozed_until: Optional[str] = None


class AlertRule(BaseModel):
    repository: str
    package_name: Optional[str] = None
    category: Optional[AlertCategory] = None
    min_severity: AlertSeverity = AlertSeverity.LOW
    snoozed_until: Optional[str] = None
    ignored: bool = False
    created_at: str


class MonitorSchedule(BaseModel):
    repository: str
    frequency: Literal["manual", "daily", "weekly", "monthly"] = "weekly"
    branches: List[str] = Field(default_factory=lambda: ["main"])
    watch_dependencies: bool = True
    auto_remediate: bool = False
    notify_on: List[AlertCategory] = Field(default_factory=lambda: [c.value for c in AlertCategory])
    digest_enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    updated_at: str


class RepositoryRiskIndex(BaseModel):
    repository: str
    overall_score: float
    outdated_dep_score: float
    security_score: float
    unsupported_score: float
    migration_debt_score: float
    dependency_count: int
    outdated_count: int
    security_issues: int
    computed_at: str


class DigestReport(BaseModel):
    repository: str
    generated_at: str
    period_start: str
    period_end: str
    new_alerts: int
    resolved_alerts: int
    health_trend: Optional[int] = None
    dependency_updates: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
