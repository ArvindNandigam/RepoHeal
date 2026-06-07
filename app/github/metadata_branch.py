import json
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
        analyzed_at = datetime.now(timezone.utc).isoformat()
        manifest = self._load_manifest(repo)
        manifest.update({
            "schema_version": max(manifest.get("schema_version", 1), 2),
            "repository": repo_id,
            "branch": self.branch_name,
            "latest_analysis_at": analyzed_at,
            "latest_files": {
                "analysis": f"{self.base_path}/snapshots/latest_analysis.json",
                "graph": f"{self.base_path}/snapshots/latest_graph.json",
                "packages": f"{self.base_path}/snapshots/latest_packages.json",
                "imports": f"{self.base_path}/snapshots/latest_imports.json",
                "dependency_risk_report": (
                    f"{self.base_path}/reports/dependency_risk_report.json"
                )
            }
        })

        files_to_commit = {
            f"{self.base_path}/metadata.json": self._json(manifest),
            f"{self.base_path}/snapshots/latest_analysis.json": self._json({
                "repository": repo_id,
                "analyzed_at": analyzed_at,
                "analysis": analysis
            }),
            f"{self.base_path}/snapshots/latest_graph.json": self._json({
                "repository": repo_id,
                "analyzed_at": analyzed_at,
                **graph
            }),
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

    def save_migration_artifacts(self, repo, document: MigrationDocument, report: HealthReport, snapshot_id: str, analysis: Dict[str, Any]) -> None:
        """Batch commit migration document, health report, and analysis snapshot to the metadata branch."""
        
        self.client.ensure_branch(repo, self.branch_name)
        
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        doc_path = f"{self.base_path}/migrations/{document.filename}"
        report_path = f"{self.base_path}/reports/health_report_{date_str}_{snapshot_id}.json"
        snapshot_path = f"{self.base_path}/snapshots/analysis_{snapshot_id}.json"
        
        generator = HealthReportGenerator()
        
        files_to_commit = {
            doc_path: document.content,
            report_path: generator.to_json(report),
            snapshot_path: json.dumps(analysis, indent=2)
        }
        
        # Batch write files
        try:
            self.client.batch_upsert_files(
                repo, 
                self.branch_name, 
                files_to_commit, 
                f"Add migration artifacts for {document.filename}"
            )
            # Update manifest
            self._update_manifest(repo, document, snapshot_id, doc_path, report_path, snapshot_path)
        except Exception as e:
            logger.error(f"Failed to batch commit artifacts: {e}")
            # Fallback to individual upserts if tree API fails
            for path, content in files_to_commit.items():
                self.client.upsert_file(repo, self.branch_name, path, content, f"Add {path}")
            self._update_manifest(repo, document, snapshot_id, doc_path, report_path, snapshot_path)

    def _update_manifest(self, repo, document: MigrationDocument, snapshot_id: str, doc_path: str, report_path: str, snapshot_path: str):
        manifest_path = f"{self.base_path}/metadata.json"
        manifest = self._load_manifest(repo)
            
        manifest.setdefault("artifacts", [])
        manifest["artifacts"].append({
            "type": "migration_run",
            "timestamp": document.timestamp,
            "snapshot_id": snapshot_id,
            "document": doc_path,
            "report": report_path,
            "snapshot": snapshot_path
        })
        
        self.client.upsert_file(
            repo, 
            self.branch_name, 
            manifest_path, 
            json.dumps(manifest, indent=2), 
            f"Update manifest for {document.filename}"
        )

    def _load_manifest(self, repo) -> Dict[str, Any]:
        manifest_path = f"{self.base_path}/metadata.json"
        try:
            contents = repo.get_contents(manifest_path, ref=self.branch_name)
            return json.loads(contents.decoded_content.decode("utf-8"))
        except Exception:
            return {"schema_version": 1, "artifacts": []}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, indent=2, default=str) + "\n"
