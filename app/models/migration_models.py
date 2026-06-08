from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

class SymbolRelationship(BaseModel):
    relation: str
    target: str
    status: str
    confidence: Optional[float] = None
    evidence_links: List[str] = Field(default_factory=list)

class VersionDistance(BaseModel):
    installed: str
    deprecated_in: Optional[str] = None
    removed_in: Optional[str] = None
    latest: str
    major_diff: int
    minor_diff: int
    patch_diff: int
    deprecated_major_diff: Optional[int] = None
    deprecated_minor_diff: Optional[int] = None
    deprecated_patch_diff: Optional[int] = None
    removed_major_diff: Optional[int] = None
    removed_minor_diff: Optional[int] = None
    removed_patch_diff: Optional[int] = None

class SymbolAssessment(BaseModel):
    symbol: str
    library: str
    installed_version: str
    latest_version: str
    status: Literal["healthy", "deprecated", "at_risk", "breaking"]
    relationships: List[SymbolRelationship] = Field(default_factory=list)
    version_distance: Optional[VersionDistance] = None
    files_using: List[str] = Field(default_factory=list)
    functions_using: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None

    def compute_confidence(self) -> Optional[float]:
        confs = [r.confidence for r in self.relationships if r.confidence is not None]
        if confs:
            return sum(confs) / len(confs)
        return None

class CorrelationResult(BaseModel):
    repository: str
    timestamp: str
    total_symbols: int
    assessments: List[SymbolAssessment] = Field(default_factory=list)
    libraries_checked: int
    webtool_errors: List[str] = Field(default_factory=list)

class AffectedFile(BaseModel):
    path: str
    lines: List[int]

class AffectedFunction(BaseModel):
    name: str
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    call_chain_depth: int

class ImpactReport(BaseModel):
    symbol: str
    affected_files: List[AffectedFile] = Field(default_factory=list)
    affected_functions: List[AffectedFunction] = Field(default_factory=list)
    affected_classes: List[str] = Field(default_factory=list)
    impact_breadth: float
    impact_depth: int

class RiskFactors(BaseModel):
    affected_file_count: int
    affected_file_percentage: float
    breaking_severity: Literal["none", "low", "medium", "high"]
    replacement_confidence: float
    version_distance_score: float
    repo_file_count: int

class RiskAssessment(BaseModel):
    symbol: str
    risk_score: int
    risk_level: Literal["low", "medium", "high"]
    factors: RiskFactors

class DependencyEntry(BaseModel):
    name: str
    installed_version: str
    latest_version: str
    status: str
    type: str

class MigrationPath(BaseModel):
    symbol: str
    target: str
    relation: str
    confidence: Optional[float] = None

class RecommendedAction(BaseModel):
    symbol: str
    priority: Literal["critical", "high", "medium", "low"]
    action_type: str
    description: str
    confidence: Optional[float] = None

class ExecutiveSummary(BaseModel):
    overall_health_score: int
    critical_findings_count: int
    deprecated_count: int
    breaking_count: int

class HealthReport(BaseModel):
    repository: str
    generated_at: str
    overall_health_score: int
    overall_risk_level: str
    executive_summary: ExecutiveSummary
    dependency_inventory: List[DependencyEntry] = Field(default_factory=list)
    deprecated_apis: List[SymbolAssessment] = Field(default_factory=list)
    breaking_changes: List[SymbolAssessment] = Field(default_factory=list)
    migration_paths: List[MigrationPath] = Field(default_factory=list)
    impact_reports: List[ImpactReport] = Field(default_factory=list)
    risk_assessment: List[RiskAssessment] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
