import logging
from typing import Dict, Any, Optional
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.remediation.pr_pipeline import RemediationPipeline

logger = logging.getLogger(__name__)

class RemediationOrchestrator:
    def __init__(self, github_client: RepoHealGitHubClient):
        self.github_client = github_client
        self.pipeline = RemediationPipeline(github_client)
        self.metadata_manager = MetadataBranchManager(github_client)

    async def process_migration(
        self,
        repo_id: str,
        analysis_id: str,
        migration_id: str,
        risk_score: int,
        patches: list
    ):
        """Route migration based on risk score."""
        if risk_score <= 30:
            # Low risk: Auto-create PR
            logger.info(f"Low risk ({risk_score}) for {migration_id}: Auto-creating PR")
            return await self.pipeline.run_remediation(repo_id, analysis_id, migration_id, patches)
        elif risk_score <= 70:
            # Medium risk: Create Draft PR
            logger.info(f"Medium risk ({risk_score}) for {migration_id}: Creating Draft PR")
            # We need to update run_remediation to support draft PRs
            return await self.pipeline.run_remediation(repo_id, analysis_id, migration_id, patches, draft=True)
        else:
            # High risk: Queue for review
            logger.info(f"High risk ({risk_score}) for {migration_id}: Queuing for dashboard review")
            self._queue_for_review(repo_id, migration_id)
            return None

    def _queue_for_review(self, repo_id: str, migration_id: str):
        repo = self.github_client.get_repo(repo_id)
        manifest = self.metadata_manager._load_manifest(repo)
        
        # Mark migration as pending review in manifest
        for mig in manifest.get("migration_reports", []):
            if mig["migration_id"] == migration_id:
                mig["status"] = "pending_review"
                
        files = {"repoheal.meta/metadata.json": self.metadata_manager._json(manifest)}
        self.github_client.batch_upsert_files(repo, self.metadata_manager.branch_name, files, f"Queue {migration_id} for review")
