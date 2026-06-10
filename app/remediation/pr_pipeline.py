import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.github.client import RepoHealGitHubClient
from app.github.changes_branch import ChangesBranchManager
from app.remediation.engine import RemediationEngine
from app.models.migration_models import HealthReport
from app.github.metadata_branch import MetadataBranchManager
from app.migrations.code_migration_engine import CodeMigrationEngine, PatchPlan, classify_patches_by_risk
from app.llm.confidence import ConfidenceLevel
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RemediationPipeline:
    def __init__(self, github_client: RepoHealGitHubClient):
        self.github_client = github_client
        self.branch_manager = ChangesBranchManager(github_client)
        self.metadata_manager = MetadataBranchManager(github_client)

    async def run_remediation(
        self,
        repo_id: str,
        analysis_id: str,
        migration_id: str,
        patches: List[Dict[str, Any]],
        draft: bool = False,
        patch_plans: Optional[List[PatchPlan]] = None,
    ):
        repo = self.github_client.get_repo(repo_id)
        default_branch = repo.default_branch

        modified_files = {}

        if patch_plans:
            plans_by_class = classify_patches_by_risk(patch_plans)
            for key in ("auto_pr", "draft_pr"):
                for plan in plans_by_class.get(key, []):
                    if plan.modified_code and plan.valid and plan.file_path:
                        modified_files[plan.file_path] = plan.modified_code
            draft = draft or bool(plans_by_class.get("draft_pr"))
        else:
            for file_path, file_patches in self._group_patches(patches).items():
                try:
                    content = repo.get_contents(file_path, ref=default_branch).decoded_content.decode("utf-8")
                    engine = RemediationEngine(content)
                    for p in file_patches:
                        self._apply_patch(engine, p)
                    if engine.modified and engine.validate():
                        modified_files[file_path] = engine.get_modified_source()
                except Exception as e:
                    logger.error(f"Patch error {file_path}: {e}")

        if not modified_files:
            return None

        lib_name = migration_id.replace("mig_", "").split("_")[0] if migration_id.startswith("mig_") else migration_id
        branches = []
        for fpath in modified_files:
            safe_name = self.branch_manager._safe_plan_name(fpath.split("/")[-1].replace(".py", ""))
            branch_name = self.branch_manager.create_changes_branch(repo, f"{migration_id}_{safe_name}")
            self.branch_manager.batch_commit_changes(
                repo, branch_name, {fpath: modified_files[fpath]},
                f"RepoHeal: {migration_id} - {fpath}"
            )
            branches.append(branch_name)

        if patch_plans:
            body = self._build_enhanced_pr_body(repo_id, analysis_id, migration_id, patch_plans, modified_files)
        else:
            body = self._build_pr_body(
                repo_id, analysis_id, migration_id, patches, modified_files,
                draft=draft,
            )

        prs = []
        for i, (fpath, branch_name) in enumerate(zip(modified_files.keys(), branches)):
            title = f"[RepoHeal] Migrate {lib_name} — {fpath.split('/')[-1]}"
            pr = self.branch_manager.create_pr(repo, branch_name, title, body, draft=draft)
            prs.append(pr)

            now_iso = datetime.now(timezone.utc).isoformat()
            pr_metadata = {
                "analysis_id": analysis_id,
                "migration_id": migration_id,
                "commit_sha": repo.get_branch(branch_name).commit.sha,
                "branch": branch_name,
                "pr_number": pr.number,
                "pr_url": pr.html_url,
                "changes_branch": branch_name,
                "created_at": now_iso,
                "status": "draft" if draft else "created",
                "is_draft": draft,
                "file_path": fpath,
                "state_history": [{"status": "draft" if draft else "created", "timestamp": now_iso}],
            }
            self._save_pr_metadata(repo, pr_metadata)

        from app.worker.metrics import record_remediation
        record_remediation(
            prs=len(prs),
            files_modified=len(modified_files),
            imports_rewritten=0,
            symbols_renamed=0,
        )

        return prs[0] if len(prs) == 1 else prs

    def _build_pr_body(
        self, repo_id: str, analysis_id: str, migration_id: str,
        patches: list, modified_files: dict, draft: bool = False,
    ) -> str:
        symbols_changed = [p.get("old", p.get("func", "unknown")) for p in patches]
        body = f"""## [RepoHeal] Automated Remediation

This PR was generated to address issues identified in analysis `{analysis_id}`.

### Details
- **Migration ID**: `{migration_id}`
- **Files Changed**: {len(modified_files)}
- **Symbols Changed**: {', '.join(symbols_changed[:10])}{'...' if len(symbols_changed) > 10 else ''}

### Changes
"""
        for fpath in modified_files:
            body += f"- `{fpath}`\n"
        body += f"\n### Evidence\n- Patches applied: {len(patches)}\n"
        body += f"\n---\n*Generated by RepoHeal{' (Draft)' if draft else ''}*"
        return body

    def _build_enhanced_pr_body(
        self, repo_id: str, analysis_id: str, migration_id: str,
        patch_plans: list, modified_files: dict,
    ) -> str:
        risk_score = max((p.risk_score for p in patch_plans if p.risk_score), default=50)
        confidences = [p.confidence_level for p in patch_plans if p.confidence_level]
        overall_conf = max(confidences, key=lambda c: {"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(c, 0)) if confidences else "MEDIUM"
        valid_count = sum(1 for p in patch_plans if p.valid)
        total = len(patch_plans)

        body = f"""## [RepoHeal] Migration Patch

This PR was generated by RepoHeal.

### Summary
- **Migration ID**: `{migration_id}`
- **Risk Score**: {risk_score}
- **Confidence**: {overall_conf}
- **Files Modified**: {len(modified_files)}
- **Patches Generated**: {total} ({valid_count} validated)

### Risk Assessment
| Metric | Value |
|---|---|
| Risk Score | {risk_score}/100 |
| Overall Confidence | {overall_conf} |
| Patches Valid | ✓ {valid_count}/{total} |

"""
        for plan in patch_plans:
            if plan.modified_code and plan.valid:
                body += f"""### `{plan.file_path}` — {plan.symbol}
- **Class**: {plan.migration_class.value}
- **Confidence**: {plan.confidence_level.value if plan.confidence_level else 'LOW'}
- **LLM Confidence**: {plan.llm_confidence:.2f}
- **Explanation**: {plan.explanation[:200]}

```
...
```
"""
        body += f"\n### Validation\n"
        for plan in patch_plans:
            if plan.validation:
                v = plan.validation
                status = "✓" if v.valid else "✗"
                body += f"- {status} `{plan.file_path}`: AST={v.ast_valid}, Syntax={v.syntax_valid}, Changed={v.has_changed}\n"

        body += f"""
### Manual Review
{'⚠️ **Manual review recommended** — some patches have medium or low confidence.' if overall_conf in ('MEDIUM', 'LOW') else '✓ Confidence is HIGH — review recommended before merge.'}

---
*Generated by RepoHeal*
"""
        return body

    def _group_patches(self, patches):
        res = {}
        for p in patches:
            res.setdefault(p["file_path"], []).append(p)
        return res

    def _apply_patch(self, engine, patch):
        t = patch["type"]
        if t == "import_rewrite":
            engine.rewrite_import(patch["old"], patch["new"])
        elif t == "symbol_rename":
            engine.rename_symbol(patch["old"], patch["new"])
        elif t == "signature_update":
            engine.update_api_signature(patch["func"], patch["kwargs"])

    def _save_pr_metadata(self, repo, pr_metadata: Dict[str, Any]):
        manifest = self.metadata_manager._load_manifest(repo)
        manifest.setdefault("pull_requests", [])
        manifest["pull_requests"].append(pr_metadata)
        pr_path = f"repoheal.meta/prs/pr_{pr_metadata['pr_number']}.json"
        files = {
            "repoheal.meta/metadata.json": self.metadata_manager._json(manifest),
            pr_path: self.metadata_manager._json(pr_metadata),
        }
        self.github_client.batch_upsert_files(
            repo, self.metadata_manager.branch_name, files,
            f"Track PR #{pr_metadata['pr_number']}"
        )
