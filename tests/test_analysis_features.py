import json
import os
import sys
import types
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

github_module = types.ModuleType("github")
github_module.Github = MagicMock
github_exception_module = types.ModuleType("github.GithubException")
github_exception_module.GithubException = type("GithubException", (Exception,), {})
sys.modules.setdefault("github", github_module)
sys.modules.setdefault("github.GithubException", github_exception_module)

neo4j_module = types.ModuleType("neo4j")
neo4j_module.GraphDatabase = MagicMock()
sys.modules.setdefault("neo4j", neo4j_module)

from app.github.metadata_branch import MetadataBranchManager
from app.intelligence.correlator import MigrationCorrelator
from app.routers import graph, webhook
from app.visualization import neo4j_graph_api
from app.visualization.page_renderer import build_graph_page
from app.worker import task_registry


class FakeCollection:
    def __init__(self):
        self.documents = []

    def find_one(self, query, projection=None):
        for document in reversed(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                result = dict(document)
                if projection and projection.get("_id") == 0:
                    result.pop("_id", None)
                return result
        return None

    def insert_one(self, document):
        self.documents.append(dict(document))

    def update_one(self, query, operation, upsert=False):
        document = self.find_one(query)
        if document is None:
            if not upsert:
                return
            document = dict(query)
            document.update(operation.get("$setOnInsert", {}))
            self.documents.append(document)

        document.update(operation.get("$set", {}))
        for key in operation.get("$unset", {}):
            document.pop(key, None)

        for index, existing in enumerate(self.documents):
            if all(existing.get(key) == value for key, value in query.items()):
                self.documents[index] = document
                break


class FakeDatabase:
    def __init__(self):
        self.jobs = FakeCollection()
        self.repository_analysis_status = FakeCollection()


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args):
        self.tasks.append((function, args))


class FakeGitHubClient:
    def __init__(self):
        self.branch = None
        self.files = None
        self.message = None

    def ensure_branch(self, repo, branch):
        self.branch = branch

    def batch_upsert_files(self, repo, branch, files, message):
        self.branch = branch
        self.files = files
        self.message = message


class MissingManifestRepo:
    def get_contents(self, path, ref):
        raise RuntimeError("manifest not found")


def test_create_job_persists_status_and_skips_recent(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(task_registry, "get_mongo_db", lambda: database)

    job_id = task_registry.create_job("owner", "repo")

    assert job_id
    assert task_registry.get_repository_status("owner", "repo")["status"] == "queued"

    task_registry.update_repository_status(
        "owner",
        "repo",
        task_registry.JobStatus.COMPLETED,
        100,
        "Analysis complete",
        job_id=job_id
    )
    assert task_registry.create_job(
        "owner",
        "repo",
        skip_if_recent=True
    ) is None


def test_webhook_queue_adds_only_new_analysis(monkeypatch):
    background_tasks = FakeBackgroundTasks()
    job_ids = iter(["job-1", None])
    monkeypatch.setattr(webhook, "create_job", lambda *args, **kwargs: next(job_ids))

    queued = webhook.queue_repository_analyses(
        background_tasks,
        [
            {"full_name": "owner/repo-1"},
            {"full_name": "owner/repo-2"},
        ]
    )

    assert queued == ["owner/repo-1"]
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0][1] == ("job-1", "owner", "repo-1")


def test_latest_analysis_batch_contains_required_files():
    client = FakeGitHubClient()
    manager = MetadataBranchManager(client)
    analysis = {
        "imports": {"files": {"main.py": {}}, "summary": {}},
        "dependencies": {"declared": {"fastapi": {}}, "count": 1},
        "dependency_graph": {"fastapi": {"version": "1.0"}},
        "issues": {"missing_count": 0},
    }

    manager.save_latest_analysis(
        MissingManifestRepo(),
        "owner/repo",
        analysis,
        {"nodes": [], "edges": [], "statistics": {}}
    )

    required_paths = {
        "repoheal.meta/metadata.json",
        "repoheal.meta/snapshots/latest_analysis.json",
        "repoheal.meta/snapshots/latest_graph.json",
        "repoheal.meta/snapshots/latest_packages.json",
        "repoheal.meta/snapshots/latest_imports.json",
        "repoheal.meta/reports/dependency_risk_report.json",
    }
    assert required_paths.issubset(set(client.files))
    assert any(
        path.startswith("repoheal.meta/snapshots/data_owner_repo_")
        and path.endswith(".json")
        for path in client.files
    )

    manifest = json.loads(client.files["repoheal.meta/metadata.json"])
    assert manifest["repository"] == "owner/repo"
    assert manifest["latest_files"]["graph"] == "repoheal.meta/snapshots/latest_graph.json"
    assert manifest["latest_files"]["graph_snapshot"].startswith(
        "repoheal.meta/snapshots/data_owner_repo_"
    )
    assert datetime.fromisoformat(manifest["latest_analysis_at"]).tzinfo == timezone.utc


def test_graph_page_polls_status_before_loading_graph():
    page = build_graph_page("owner", "repo", "user")

    assert "while (status.status !== \"completed\")" in page
    assert page.index("await waitForAnalysis();") < page.index(
        "`/graph/${repoOwner}/${repoName}`"
    )
    assert "Graph API returned no nodes" in page
    assert "Please keep this page open" in page
    assert "@keyframes buildPulse" in page


def test_stale_finalizing_analysis_can_serve_completed_graph():
    old_status = {
        "status": "running",
        "progress": 90,
        "updated_at": (
            datetime.now(timezone.utc) - timedelta(minutes=6)
        ).isoformat()
    }
    fresh_status = {
        **old_status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    assert graph._is_stale_finalizing_status(old_status) is True
    assert graph._is_stale_finalizing_status(fresh_status) is False


def test_graph_endpoint_falls_back_to_metadata_branch_when_cache_is_empty(monkeypatch):
    monkeypatch.setattr(
        graph,
        "get_session_data",
        lambda user: {"github_token": "token"}
    )
    monkeypatch.setattr(
        graph,
        "ensure_repoheal_installed",
        lambda repo_owner, repo_name: {"id": 123}
    )
    monkeypatch.setattr(
        graph,
        "verify_repository_access",
        lambda **kwargs: True
    )
    monkeypatch.setattr(
        graph,
        "get_analysis_status",
        lambda repo_owner, repo_name: {
            "status": "completed",
            "progress": 100,
            "message": "Analysis complete"
        }
    )
    monkeypatch.setattr(
        graph,
        "load_cached_analysis",
        lambda repo_owner, repo_name: {"imports": {"files": {}}}
    )
    monkeypatch.setattr(
        graph,
        "_build_metadata_graph",
        lambda repo_id, installation_id: {
            "nodes": [
                {"data": {"id": repo_id, "label": repo_id, "type": "repository"}}
            ],
            "edges": [],
            "statistics": {"metadata_stats": {"source": "repoheal.meta"}}
        }
    )

    response = asyncio.run(
        graph.get_graph_visualization(
            MagicMock(),
            "owner",
            "repo",
            user={"session_id": "session", "github_login": "user"}
        )
    )

    assert response["repository"] == "owner/repo"
    assert response["nodes"]
    assert response["statistics"]["metadata_stats"]["source"] == "repoheal.meta"


def test_status_requires_visual_graph_before_completed(monkeypatch):
    class FakeResult:
        def single(self):
            return {"file_count": 12, "package_count": 4}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def run(self, query, **kwargs):
            return FakeResult()

    monkeypatch.setattr(
        graph,
        "get_session_data",
        lambda user: {"github_token": "token"}
    )
    monkeypatch.setattr(
        graph,
        "ensure_repoheal_installed",
        lambda repo_owner, repo_name: {"id": 123}
    )
    monkeypatch.setattr(
        graph,
        "verify_repository_access",
        lambda **kwargs: True
    )
    monkeypatch.setattr(
        graph,
        "get_analysis_status",
        lambda repo_owner, repo_name: {
            "status": "completed",
            "progress": 100,
            "message": "Analysis complete"
        }
    )
    monkeypatch.setattr(
        graph,
        "load_cached_analysis",
        lambda repo_owner, repo_name: {"imports": {"files": {}}}
    )
    monkeypatch.setattr(
        graph,
        "_build_metadata_graph",
        lambda repo_id, installation_id: None
    )
    monkeypatch.setattr(
        graph.neo4j_connection,
        "get_session",
        lambda: FakeSession()
    )

    response = asyncio.run(
        graph.get_repository_status(
            MagicMock(),
            "owner",
            "repo",
            user={"session_id": "session", "github_login": "user"}
        )
    )

    assert response["status"] == "not_started"
    assert response["message"] == "Graph snapshot missing; analysis must be rerun"
    assert response["files"] == 12
    assert response["packages"] == 4


def test_neo4j_visualizer_includes_repository_root(monkeypatch):
    class FakeNode(dict):
        def __init__(self, labels, values):
            super().__init__(values)
            self.labels = labels

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def run(self, query, **kwargs):
            if "MATCH (n)" in query:
                return [
                    {
                        "n": FakeNode(
                            {"Repository"},
                            {"id": "owner/repo"}
                        )
                    }
                ]
            return []

    monkeypatch.setattr(
        neo4j_graph_api.neo4j_connection,
        "get_session",
        lambda: FakeSession()
    )

    payload = neo4j_graph_api.Neo4jGraphVisualizer.to_cytoscape_format(
        "owner/repo"
    )

    assert payload["nodes"][0]["data"]["id"] == "owner/repo"
    assert payload["nodes"][0]["data"]["type"] == "repository"


def test_correlator_uses_bulk_and_filters_false_libraries():
    class FakeWebtoolClient:
        def __init__(self):
            self.calls = []

        async def get_bulk_intelligence(self, libraries):
            self.calls.append(libraries)
            return {
                "results": [
                    {
                        "library": "numpy",
                        "latest_version": "2.0.0",
                        "results": [
                            {
                                "symbol": "numpy.array",
                                "relationships": []
                            }
                        ]
                    },
                    {
                        "library": "torch",
                        "latest_version": "3.0.0",
                        "results": [
                            {
                                "symbol": "torch.load",
                                "relationships": []
                            }
                        ]
                    }
                ]
            }

    client = FakeWebtoolClient()
    result = asyncio.run(
        MigrationCorrelator(client).correlate(
            {
                "fingerprints": {
                    "numpy": {"version": "1.0.0", "symbols": ["numpy.array"]},
                    "torch": {"version": "2.0.0", "symbols": ["torch.load"]},
                    "os": {"version": "unknown", "symbols": ["os.path"]},
                    "df": {"version": "unknown", "symbols": ["df.merge"]},
                },
                "dependency_graph": {
                    "numpy": {"latest_version": "2.0.0"},
                    "torch": {"latest_version": "3.0.0"},
                    "os": {"latest_version": "unknown"},
                }
            },
            "owner/repo"
        )
    )

    assert len(client.calls) == 1
    assert [item["library"] for item in client.calls[0]] == ["numpy", "torch"]
    assert result.libraries_checked == 2
    assert len(result.assessments) == 2
