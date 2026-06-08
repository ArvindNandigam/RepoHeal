import logging
from datetime import datetime, timezone
from typing import Dict, Any
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager

logger = logging.getLogger(__name__)

class PRTracker:
    TRACKED_STATES = ["created", "draft", "review_requested", "approved", "changes_requested", "merged", "closed"]

    def __init__(self, github_client: RepoHealGitHubClient):
        self.github_client = github_client
        self.metadata_manager = MetadataBranchManager(github_client)

    def handle_webhook_event(self, payload: Dict[str, Any]):
        """Handle 'pull_request' webhook event with state history tracking."""
        action = payload.get("action")
        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})
        
        pr_number = pr_data.get("number")
        repo_full_name = repo_data.get("full_name")
        
        if not pr_number or not repo_full_name:
            return
            
        logger.info(f"PR event received: {repo_full_name} PR #{pr_number} - {action}")
        
        # Check if this PR is tracked by RepoHeal
        repo = self.github_client.get_repo(repo_full_name)
        manifest = self.metadata_manager._load_manifest(repo)
        
        pr_meta = next((p for p in manifest.get("pull_requests", []) if p["pr_number"] == pr_number), None)
        if not pr_meta:
            return # Not a RepoHeal-managed PR
            
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Map GitHub action + state to status
        new_status = self._map_github_status(pr_data, action)
        pr_meta["status"] = new_status
        pr_meta["updated_at"] = now_iso
        
        if action == "closed" and pr_data.get("merged"):
            new_status = "merged"
            pr_meta["status"] = "merged"
        
        # Track state history
        state_history = pr_meta.get("state_history", [])
        if not state_history or state_history[-1].get("status") != new_status:
            state_history.append({
                "status": new_status,
                "timestamp": now_iso,
                "action": action
            })
        pr_meta["state_history"] = state_history
            
        # Save manifest and PR record
        pr_path = f"repoheal.meta/prs/pr_{pr_number}.json"
        files = {
            "repoheal.meta/metadata.json": self.metadata_manager._json(manifest),
            pr_path: self.metadata_manager._json(pr_meta)
        }
        self.github_client.batch_upsert_files(repo, self.metadata_manager.branch_name, files, f"Update PR #{pr_number} status to {new_status}")

    def _map_github_status(self, pr_data: Dict[str, Any], action: str = "") -> str:
        state = pr_data.get("state")
        draft = pr_data.get("draft")
        merged = pr_data.get("merged")
        
        if merged: return "merged"
        if state == "closed": return "closed"
        
        # Map GitHub-specific actions to our tracked states
        if action == "review_requested": return "review_requested"
        if action == "approved": return "approved"
        if action == "changes_requested": return "changes_requested"
        
        if draft: return "draft"
        if state == "open": return "open"
        return "open"
