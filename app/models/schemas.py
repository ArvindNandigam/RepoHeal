from typing import List, Dict, Any, Optional
from pydantic import BaseModel

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
    workspace_url: str

class DashboardResponse(BaseModel):
    user: str
    repositories: List[RepositoryConfig]

class WorkspaceResponse(BaseModel):
    repo_owner: str
    repo_name: str
    user: str
    workspace_url: str
    status: str

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
