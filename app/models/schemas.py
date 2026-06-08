from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class AnalysisTargetMetadata(BaseModel):
    analysis_id: str
    repository_snapshot_id: str
    repository: str
    branch: str
    commit_sha: str
    short_commit: str
    analysis_timestamp: str
    analysis_version: str = "1.0"
    schema_version: str = "2.0"

class ComparisonMetadata(BaseModel):
    comparison_id: str
    repository: str
    left_analysis_id: str
    right_analysis_id: str
    left_branch: str
    left_commit: str
    right_branch: str
    right_commit: str
    created_at: str

class PRMetadata(BaseModel):
    analysis_id: str
    migration_id: Optional[str] = None
    comparison_id: Optional[str] = None
    repository_snapshot_id: str
    commit_sha: str
    branch: str
    pr_number: int
    pr_url: str
    changes_branch: str
    created_at: str
    status: str = "open"

class RepositoryConfig(BaseModel):
    name: str
    owner: str
    repo: str
    private: bool
    analyze_url: str
    reanalyze_url: str
    health_refresh_url: str
    status_url: str
    visualize_url: str
    reports_url: str
    reports_hub_url: str = ""
    history_url: str = ""
    compare_url: str

class DashboardResponse(BaseModel):
    user: str
    repositories: List[RepositoryConfig]
    timezone: Optional[str] = "UTC"

class WorkspaceResponse(BaseModel):
    repo_owner: str
    repo_name: str
    user: str
    status: str

class AnalysisTarget(BaseModel):
    mode: str = "latest"
    branch: Optional[str] = None
    commit_sha: Optional[str] = None

class AnalysisResponse(BaseModel):
    repository: str
    status: str
    analysis: Dict[str, Any]
    graph_url: str
    visualize_url: str
    timestamp: str

class RepositoryStatus(BaseModel):
    repository: str
    status: str
    progress: int = 0
    message: str = "Analysis has not started"
    files: Optional[int] = None
    packages: Optional[int] = None
    last_analysis: Optional[str] = None
    last_health_refresh: Optional[str] = None
    last_commit_analyzed: Optional[str] = None
    current_head: Optional[str] = None
    selected_branch: Optional[str] = None
    code_state_status: Optional[str] = None
    analysis_id: Optional[str] = None
    repository_snapshot_id: Optional[str] = None

class CompareAnalysesRequest(BaseModel):
    branch_a: str
    commit_a: str
    branch_b: str
    commit_b: str

class CompareAnalysesResponse(BaseModel):
    repository: str
    comparison_path: str
    comparison: Dict[str, Any]

class GraphResponse(BaseModel):
    repository: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    statistics: Dict[str, Any]

class GraphBuildingResponse(BaseModel):
    repository: str
    status: str
    progress: int
    message: str

class WebhookResponse(BaseModel):
    received: bool
    event: Optional[str] = None
    action: Optional[str] = None
    bootstrapped_repositories: Optional[List[str]] = None
    queued_repositories: Optional[List[str]] = None
    added: Optional[int] = None
    removed: Optional[int] = None
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    mongodb: Optional[str] = None
    version: Optional[str] = None
    authentication: Optional[str] = None
    documentation: Optional[str] = None
    login_url: Optional[str] = None

class UpgradeSpec(BaseModel):
    library: str
    from_version: str
    to_version: str

class SimulateUpgradeRequest(BaseModel):
    upgrades: List[UpgradeSpec]

class SimulatedUpgradeResult(BaseModel):
    library: str
    from_version: str
    to_version: str
    symbol_count: int
    impacted_files: List[str]
    breaking_apis: List[str]
    auto_fixable_count: int
    manual_review_count: int
    risk_score: float
    risk_level: str
    confidence: Optional[float] = None

class SimulateUpgradeResponse(BaseModel):
    repository: str
    generated_at: str
    analysis_id: str
    upgrades: List[SimulatedUpgradeResult]
    overall_risk_score: float
    overall_risk_level: str

class RebuildGraphRequest(BaseModel):
    analysis_id: Optional[str] = None
    branch: Optional[str] = None
    commit: Optional[str] = None

class RebuildGraphResponse(BaseModel):
    repository: str
    status: str
    nodes_created: int
    edges_created: int
    message: str
