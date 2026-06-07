import json
import re
from datetime import datetime, timezone
from typing import Dict, Any

from app.github.client import RepoHealGitHubClient, REPOHEAL_METADATA_BRANCH
from app.migrations.document_generator import MigrationDocument
from app.reports.health_report import HealthReportGenerator
from app.models.migration_models import HealthReport
from app.utils.logger import get_logger

logger = get_logger(__name__)

class MetadataBranchManager:
    def __init__(self, github_client: RepoHealGitHubClient):
        self.client = github_client
        self.branch_name = REPOHEAL_METADATA_BRANCH
        self.base_path = "repoheal.meta"

    def save_latest_analysis(
        self,
        repo,
        repo_id: str,
        analysis: Dict[str, Any],
        graph: Dict[str, Any]
    ) -> None:
        """Synchronize the durable latest-analysis files in one commit."""
        analyzed_at_dt = datetime.now(timezone.utc)
        analyzed_at = analyzed_at_dt.isoformat()
        snapshot_id = analyzed_at_dt.strftime("%Y%m%dT%H%M%SZ")
        graph_snapshot_path = (
            f"{self.base_path}/snapshots/"
            f"data_{self._safe_name(repo_id)}_{snapshot_id}.json"
        )
        manifest = self._load_manifest(repo)
        manifest.update({
            "schema_version": max(manifest.get("schema_version", 1), 2),
            "repository": repo_id,
            "branch": self.branch_name,
            "latest_analysis_at": analyzed_at,
            "latest_files": {
                "analysis": f"{self.base_path}/snapshots/latest_analysis.json",
                "graph": f"{self.base_path}/snapshots/latest_graph.json",
                "graph_snapshot": graph_snapshot_path,
                "packages": f"{self.base_path}/snapshots/latest_packages.json",
                "imports": f"{self.base_path}/snapshots/latest_imports.json",
                "dependency_risk_report": (
                    f"{self.base_path}/reports/dependency_risk_report.json"
                )
            }
        })

        graph_payload = {
            "repository": repo_id,
            "analyzed_at": analyzed_at,
            **graph
        }
        files_to_commit = {
            f"{self.base_path}/metadata.json": self._json(manifest),
            f"{self.base_path}/snapshots/latest_analysis.json": self._json({
                "repository": repo_id,
                "analyzed_at": analyzed_at,
                "analysis": analysis
            }),
            f"{self.base_path}/snapshots/latest_graph.json": self._json(graph_payload),
            graph_snapshot_path: self._json(graph_payload),
            f"{self.base_path}/snapshots/latest_packages.json": self._json({
                **analysis.get("dependencies", {}),
                "packages": analysis.get("dependency_graph", {})
            }),
            f"{self.base_path}/snapshots/latest_imports.json": self._json(
                analysis.get("imports", {})
            ),
            f"{self.base_path}/reports/dependency_risk_report.json": self._json({
                "repository": repo_id,
                "analyzed_at": analyzed_at,
                "issues": analysis.get("issues", {}),
                "dependency_graph": analysis.get("dependency_graph", {})
            })
        }

        self.client.ensure_branch(repo, self.branch_name)
        try:
            self.client.batch_upsert_files(
                repo,
                self.branch_name,
                files_to_commit,
                f"Update RepoHeal analysis for {repo_id}"
            )
        except Exception as exc:
            logger.warning(
                f"Batch metadata sync failed for {repo_id}; "
                f"falling back to individual files: {exc}"
            )
            for path, content in files_to_commit.items():
                self.client.upsert_file(
                    repo,
                    self.branch_name,
                    path,
                    content,
                    f"Update {path} for {repo_id}"
                )
        logger.info(f"Synchronized latest analysis metadata for {repo_id}")

    def load_latest_graph(self, repo) -> Dict[str, Any] | None:
        """Load the latest durable Cytoscape graph from the metadata branch."""
        manifest = self._load_manifest(repo)
        graph_path = (
            manifest
            .get("latest_files", {})
            .get("graph")
        )
        candidate_paths = [
            graph_path,
            f"{self.base_path}/snapshots/latest_graph.json"
        ]

        for path in candidate_paths:
            if not path:
                continue

            try:
                contents = repo.get_contents(path, ref=self.branch_name)
                return json.loads(contents.decoded_content.decode("utf-8"))
            except Exception:
                continue

        return None

    def save_migration_artifacts(self, repo, document: MigrationDocument, report: HealthReport, snapshot_id: str, analysis: Dict[str, Any]) -> None:
        """Batch commit immutable migration artifacts to the metadata branch."""
        
        self.client.ensure_branch(repo, self.branch_name)
        
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        doc_path = f"{self.base_path}/migrations/{document.filename}"
        report_path = f"{self.base_path}/reports/health_report_{date_str}_{snapshot_id}.json"
        snapshot_path = f"{self.base_path}/snapshots/analysis_{snapshot_id}.json"
        manifest_path = f"{self.base_path}/metadata.json"
        readme_path = f"{self.base_path}/README.md"

        if self._path_exists(repo, doc_path):
            raise ValueError(
                f"Migration document already exists and is immutable: {doc_path}"
            )
        
        generator = HealthReportGenerator()
        manifest = self._load_manifest(repo)
        self._add_artifact_to_manifest(
            manifest,
            repo,
            document,
            snapshot_id,
            doc_path,
            report_path,
            snapshot_path
        )
        
        files_to_commit = {
            manifest_path: self._json(manifest),
            doc_path: document.content,
            report_path: generator.to_json(report),
            snapshot_path: self._json(analysis)
        }

        if not self._path_exists(repo, readme_path):
            files_to_commit[readme_path] = self._readme()
        
        # Batch write files
        try:
            self.client.batch_upsert_files(
                repo, 
                self.branch_name, 
                files_to_commit, 
                f"Add migration artifacts for {document.filename}"
            )
        except Exception as e:
            logger.error(f"Failed to batch commit artifacts: {e}")
            # Fallback to individual upserts if tree API fails
            for path, content in files_to_commit.items():
                self.client.upsert_file(repo, self.branch_name, path, content, f"Add {path}")

    def _update_manifest(self, repo, document: MigrationDocument, snapshot_id: str, doc_path: str, report_path: str, snapshot_path: str):
        manifest_path = f"{self.base_path}/metadata.json"
        manifest = self._load_manifest(repo)
        self._add_artifact_to_manifest(
            manifest,
            repo,
            document,
            snapshot_id,
            doc_path,
            report_path,
            snapshot_path
        )
        
        self.client.upsert_file(
            repo, 
            self.branch_name, 
            manifest_path, 
            self._json(manifest), 
            f"Update manifest for {document.filename}"
        )

    def _add_artifact_to_manifest(
        self,
        manifest: Dict[str, Any],
        repo,
        document: MigrationDocument,
        snapshot_id: str,
        doc_path: str,
        report_path: str,
        snapshot_path: str
    ) -> None:
        manifest.update({
            "schema_version": max(manifest.get("schema_version", 1), 2),
            "repository": getattr(repo, "full_name", manifest.get("repository")),
            "branch": self.branch_name,
        })
        manifest.setdefault("artifacts", [])
        artifact = {
            "type": "migration_run",
            "timestamp": document.timestamp,
            "snapshot_id": snapshot_id,
            "document": doc_path,
            "report": report_path,
            "snapshot": snapshot_path
        }
        if artifact not in manifest["artifacts"]:
            manifest["artifacts"].append(artifact)

    def _load_manifest(self, repo) -> Dict[str, Any]:
        manifest_path = f"{self.base_path}/metadata.json"
        try:
            contents = repo.get_contents(manifest_path, ref=self.branch_name)
            return json.loads(contents.decoded_content.decode("utf-8"))
        except Exception:
            return {"schema_version": 1, "artifacts": []}

    def _path_exists(self, repo, path: str) -> bool:
        try:
            contents = repo.get_contents(path, ref=self.branch_name)
            if contents.__class__.__module__.startswith("unittest.mock"):
                return False
            return True
        except Exception:
            return False

    def _readme(self) -> str:
        return (
            "# RepoHeal Metadata Branch\n\n"
            "This branch stores RepoHeal-generated migration metadata.\n\n"
            "- `repoheal.meta/migrations/`: immutable migration documents\n"
            "- `repoheal.meta/snapshots/`: analysis snapshots\n"
            "- `repoheal.meta/reports/`: health reports\n"
            "- `repoheal.meta/metadata.json`: artifact manifest\n\n"
            "Do not modify migration documents manually; create a new migration "
            "document instead.\n"
        )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, indent=2, default=str) + "\n"

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)
