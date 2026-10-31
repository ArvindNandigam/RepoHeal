import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.graph.graph_builder import Neo4jGraphBuilder
from app.visualization.neo4j_graph_api import Neo4jGraphVisualizer
from app.worker.metrics import (
    ensure_platform_metrics_initialized,
    get_all_metrics,
    count_repository,
    count_analysis,
    count_commit,
    count_branch,
    record_code_scale,
    record_graph_scale,
    record_dependency_intelligence,
    record_impact_analysis,
    record_migration_metrics,
    record_monitoring_metrics,
)
from app.routers.admin import _platform_metrics_status


client = TestClient(app)


# --- 1. Graph: Neo4j Write and Read Verification ---

def test_neo4j_graph_builder_and_visualizer_logic():
    """Verify that Neo4jGraphBuilder issues the correct Cypher queries for nodes/edges

    and Neo4jGraphVisualizer reconstructs them into Cytoscape format.
    """
    mock_session = MagicMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__.return_value = mock_session
    mock_session_ctx.__exit__.return_value = None

    analysis_data = {
        "imports": {
            "files": {
                "main.py": {
                    "source": "import",
                    "normalized": ["requests", "fastapi.routing"],
                }
            }
        },
        "semantic_graph": {
            "files": {
                "main.py": {
                    "functions": [{"name": "app_handler", "start_line": 10, "end_line": 20}],
                    "classes": [{"name": "AppConfig", "start_line": 25, "end_line": 40}],
                    "calls": [{"caller": "app_handler", "callee": "requests.get"}],
                    "apis": [{"name": "requests.get", "function": "app_handler", "line": 15}],
                }
            }
        },
        "dependency_graph": {
            "requests": {"version": "2.31.0", "type": "production"},
            "fastapi": {"version": "0.110.0", "type": "production"},
        },
    }

    builder = Neo4jGraphBuilder()
    with patch("app.graph.graph_builder.neo4j_connection.get_session", return_value=mock_session_ctx):
        builder.build_graph("test_owner/test_repo", analysis_data)

    # Verify session.run was called for Repository, Files, Namespaces, Functions, Classes, Calls, and APIs
    assert mock_session.run.call_count >= 5
    run_queries = [call.args[0] for call in mock_session.run.call_args_list if call.args]
    assert any("Repository" in q for q in run_queries)
    assert any("File" in q for q in run_queries)
    assert any("Function" in q for q in run_queries)

    # Now verify reading nodes and edges via Neo4jGraphVisualizer
    class MockNode(dict):
        def __init__(self, data, labels):
            super().__init__(data)
            self.labels = labels

    n1 = MockNode({"id": "test_owner/test_repo", "name": "test_owner/test_repo"}, ["Repository"])
    n2 = MockNode({"id": "test_owner/test_repo:file:main.py", "path": "main.py", "name": "main.py"}, ["File"])
    mock_nodes_record = [{"n": n1}, {"n": n2}]
    mock_edges_record = [{"a": n1, "b": n2, "rel": "CONTAINS"}]

    mock_read_session = MagicMock()
    mock_read_session.run.side_effect = [mock_nodes_record, mock_edges_record]
    mock_read_ctx = MagicMock()
    mock_read_ctx.__enter__.return_value = mock_read_session
    mock_read_ctx.__exit__.return_value = None

    with patch("app.visualization.neo4j_graph_api.neo4j_connection.get_session", return_value=mock_read_ctx):
        cytoscape_data = Neo4jGraphVisualizer.to_cytoscape_format("test_owner/test_repo")

    assert "nodes" in cytoscape_data
    assert "edges" in cytoscape_data
    assert len(cytoscape_data["nodes"]) == 2
    assert len(cytoscape_data["edges"]) == 1
    assert cytoscape_data["edges"][0]["data"]["relationship"] == "CONTAINS"


# --- 2. Graph Router States: Unanalyzed, Building, Empty, Live ---

@pytest.mark.asyncio
async def test_graph_endpoint_not_analyzed_state():
    """Verify that an unanalyzed repo returns status 'not_analyzed' and message 'Run analysis first'."""
    from app.routers.graph import get_graph_visualization
    from starlette.requests import Request

    mock_user = {"github_login": "test_user"}
    mock_req = Request({
        "type": "http",
        "method": "GET",
        "path": "/graph/test_owner/unstarted_repo",
        "url": "http://testserver/graph/test_owner/unstarted_repo",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    })

    with patch("app.routers.graph.get_session_data", return_value={"github_token": "mock_token"}), \
         patch("app.routers.graph.ensure_repoheal_installed", return_value={"id": 12345}), \
         patch("app.routers.graph.verify_repository_access", return_value=True), \
         patch("app.routers.graph.get_analysis_status", return_value={"status": "not_analyzed", "progress": 0, "last_analysis": None}), \
         patch("app.routers.graph.load_cached_analysis", return_value=None), \
         patch("app.routers.graph.neo4j_connection.is_available", return_value=False):
        
        result = await get_graph_visualization(
            request=mock_req,
            repo_owner="test_owner",
            repo_name="unstarted_repo",
            analysis_id=None,
            user=mock_user,
        )

        assert result["status"] == "not_analyzed"
        assert result["message"] == "Run analysis first"
        assert result["nodes"] == []
        assert result["edges"] == []


@pytest.mark.asyncio
async def test_graph_endpoint_empty_graph_state():
    """Verify that an analysis that completed with 0 nodes returns status 'empty'."""
    from app.routers.graph import get_graph_visualization
    from starlette.requests import Request

    mock_user = {"github_login": "test_user"}
    mock_req = Request({
        "type": "http",
        "method": "GET",
        "path": "/graph/test_owner/empty_repo",
        "url": "http://testserver/graph/test_owner/empty_repo",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    })

    with patch("app.routers.graph.get_session_data", return_value={"github_token": "mock_token"}), \
         patch("app.routers.graph.ensure_repoheal_installed", return_value={"id": 12345}), \
         patch("app.routers.graph.verify_repository_access", return_value=True), \
         patch("app.routers.graph.get_analysis_status", return_value={"status": "completed", "progress": 100, "last_analysis": "2026-10-31T09:00:00"}), \
         patch("app.routers.graph.load_cached_analysis", return_value={}), \
         patch("app.routers.graph._build_cached_graph", return_value=None), \
         patch("app.routers.graph._build_metadata_graph", return_value=None), \
         patch("app.routers.graph.neo4j_connection.is_available", return_value=False):
        
        result = await get_graph_visualization(
            request=mock_req,
            repo_owner="test_owner",
            repo_name="empty_repo",
            analysis_id=None,
            user=mock_user,
        )

        assert result["status"] == "empty"
        assert "No nodes or relationships" in result["message"]


# --- 3. Reports Router: Export, History, Compare, Health ---

@pytest.mark.asyncio
async def test_reports_history_and_compare():
    """Verify history and compare endpoints return correct structures."""
    from app.routers.reports import get_analysis_history, compare_reports

    mock_user = {"github_login": "test_user"}
    mock_manifest = {
        "analyses": [
            {"analysis_id": "aid_1", "branch": "main", "commit": "abc1234", "timestamp": "2026-10-30T10:00:00"},
            {"analysis_id": "aid_2", "branch": "main", "commit": "def5678", "timestamp": "2026-10-31T10:00:00"},
        ],
        "health_reports": [
            {"analysis_id": "aid_1", "health_score": 75},
            {"analysis_id": "aid_2", "health_score": 90},
        ],
        "last_analyzed_commit": "def5678",
    }

    mock_client = MagicMock()
    mock_repo = MagicMock()
    mock_repo.default_branch = "main"
    mock_client.get_repo.return_value = mock_repo

    with patch("app.routers.reports.get_session_data", return_value={"github_token": "mock_token"}), \
         patch("app.routers.reports.ensure_repoheal_installed", return_value={"id": 12345}), \
         patch("app.routers.reports.verify_repository_access", return_value=True), \
         patch("app.routers.reports.RepoHealGitHubClient", return_value=mock_client), \
         patch("app.routers.reports.MetadataBranchManager._load_manifest", return_value=mock_manifest):
        
        history = await get_analysis_history("owner", "repo", None, mock_user)
        assert len(history["timeline"]) == 2
        assert history["timeline"][0]["analysis_id"] == "aid_2"
        assert history["timeline"][0]["health_score"] == 90

        # Compare the two analyses
        comparison = await compare_reports("owner", "repo", None, None, mock_user)
        assert comparison["available"] is True
        assert comparison["left"]["health_score"] == 75
        assert comparison["right"]["health_score"] == 90
        # Delta score: 90 - 75 = 15
        delta_change = next(c for c in comparison["changes"] if c["metric"] == "health_score")
        assert delta_change["delta"] == 15


@pytest.mark.asyncio
async def test_reports_markdown_export():
    """Verify health report markdown export formatting."""
    from app.routers.reports import export_report

    mock_user = {"github_login": "test_user"}
    mock_report = {
        "overall_health_score": 88,
        "overall_risk_score": 25,
        "generated_at": "2026-10-31T09:00:00Z",
        "recommended_actions": [
            {"priority": "high", "symbol": "flask.Flask.before_request", "description": "Replace with before_app_request"}
        ],
    }

    with patch("app.routers.reports.get_health_report_data", return_value=mock_report):
        response = await export_report("owner", "repo", format="markdown", analysis_id=None, user=mock_user)
        content = response.body.decode("utf-8")
        assert "# RepoHeal health report: owner/repo" in content
        assert "Health score: 88" in content
        assert "flask.Flask.before_request" in content
        assert "attachment" in response.headers["Content-Disposition"]


# --- 4. Admin Metrics: Initialization and Status Verification ---

def test_admin_metrics_collection_and_status():
    """Verify platform metrics initialization and coverage without inventing values."""
    mock_db = MagicMock()
    mock_platform_collection = MagicMock()
    mock_db.platform_metrics = mock_platform_collection

    # Initially collection is empty
    mock_platform_collection.find.return_value = []

    with patch("app.worker.metrics.get_mongo_db", return_value=mock_db), \
         patch("app.routers.admin.get_mongo_db", return_value=mock_db):
        
        ensure_platform_metrics_initialized()
        # Verify all 14 expected metrics were upserted
        assert mock_platform_collection.update_one.call_count >= 14

        # Now simulate all 14 metrics present in mongo
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        mock_docs = [
            {"metric": m, "updated_at": now, "count": 1 if m == "analyses_performed" else 0}
            for m in [
                "repositories_analyzed", "analyses_performed", "commits_analyzed",
                "branches_analyzed", "installations", "code_scale", "graph_scale",
                "dependency_intelligence", "impact_analysis", "migration_metrics",
                "remediation", "monitoring", "performance", "failure_reasons",
            ]
        ]
        mock_platform_collection.find.return_value = mock_docs

        status = _platform_metrics_status()
        assert status["state"] == "collected"
        assert status["missing_metrics"] == []
        assert "Values are persisted platform metrics" in status["message"]


def test_zero_sized_graph_metrics_are_recorded_as_zero(monkeypatch):
    from app.worker import metrics

    mock_db = MagicMock()
    mock_db.platform_metrics.find_one.return_value = None
    monkeypatch.setattr(metrics, "get_mongo_db", lambda: mock_db)

    metrics.record_graph_scale("owner/repo", 0, 0)

    update = mock_db.platform_metrics.update_one.call_args.args[1]
    assert update["$inc"] == {"total_nodes": 0, "total_edges": 0, "graph_count": 0}


# --- 5. Legal Pages Design Language ---

def test_legal_pages_rendered_with_repoheal_design():
    """Verify /privacy and /terms-of-service respond with 200 and contain the RepoHeal design language."""
    privacy_res = client.get("/privacy")
    assert privacy_res.status_code == 200
    assert "Privacy Policy · RepoHeal" in privacy_res.text
    assert "♥" in privacy_res.text
    assert "Manrope" in privacy_res.text
    assert "Terms of Service" in privacy_res.text

    terms_res = client.get("/terms-of-service")
    assert terms_res.status_code == 200
    assert "Terms of Service · RepoHeal" in terms_res.text
    assert "♥" in terms_res.text
    assert "Important Beta Notice" in terms_res.text
