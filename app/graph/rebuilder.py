import json
from typing import Dict, Any, List
from app.graph.graph_builder import Neo4jGraphBuilder
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GraphRebuilder:
    def __init__(self, github_client: RepoHealGitHubClient):
        self.github_client = github_client
        self.metadata = MetadataBranchManager(github_client)
        self.builder = Neo4jGraphBuilder()

    def rebuild(
        self,
        repo_id: str,
        analysis_id: str | None = None,
        branch: str | None = None,
        commit: str | None = None
    ) -> Dict[str, Any]:
        repo = self.github_client.get_repo(repo_id)
        manifest = self.metadata._load_manifest(repo)
        analyses = manifest.get("analyses", [])
        if not isinstance(analyses, list):
            analyses = []

        targets: List[Dict[str, Any]] = []
        if analysis_id:
            meta = next((a for a in analyses if a.get("analysis_id") == analysis_id), None)
            if meta:
                targets.append(meta)
        elif branch and commit:
            short = commit[:7]
            for a in analyses:
                if a.get("branch") == branch and a.get("commit", "").startswith(short):
                    targets.append(a)
        else:
            latest = manifest.get("latest_analysis_id")
            if latest:
                meta = next((a for a in analyses if a.get("analysis_id") == latest), None)
                if meta:
                    targets.append(meta)
            if not targets and analyses:
                targets.append(analyses[-1])

        if not targets:
            return {
                "repository": repo_id,
                "status": "error",
                "nodes_created": 0,
                "edges_created": 0,
                "message": "No analysis records found to rebuild"
            }

        total_nodes = 0
        total_edges = 0

        self.builder.clear_repository_graph(repo_id)

        for target in targets:
            aid = target.get("analysis_id", "unknown")
            logger.info(f"Rebuilding Neo4j graph from analysis {aid}")

            record = self.metadata.load_analysis_record(
                repo,
                target.get("branch", "main"),
                target.get("commit", "")
            )
            if not record:
                logger.warning(f"Could not load analysis record for {aid}, skipping")
                continue

            analysis = record.get("analysis", {})
            if not analysis:
                logger.warning(f"Analysis data empty for {aid}, skipping")
                continue

            self.builder.build_graph(repo_id, analysis)

        return {
            "repository": repo_id,
            "status": "completed",
            "nodes_created": total_nodes,
            "edges_created": total_edges,
            "message": f"Graph rebuilt from {len(targets)} analysis record(s)"
        }
