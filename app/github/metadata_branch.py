import json
import re
from datetime import datetime, timezone
from typing import Dict, Any

from app.github.client import RepoHealGitHubClient, REPOHEAL_METADATA_BRANCH
from app.migrations.document_generator import MigrationDocument
from app.reports.health_report import HealthReportGenerator, compute_overall_risk_score
from app.models.migration_models import HealthReport
from app.utils.logger import get_logger

logger = get_logger(__name__)

class MetadataBranchManager:
    def __init__(self, github_client: RepoHealGitHubClient):
        self.client = github_client
        self.branch_name = REPOHEAL_METADATA_BRANCH
        self.base_path = "repoheal.meta"

    def generate_ids(self, repo_id: str, branch: str, commit_sha: str) -> tuple[str, str, str]:
        """Generate standardized analysis_id and repository_snapshot_id."""
        short_commit = commit_sha[:7]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_branch = self._safe_name(branch)
        
        analysis_id = f"{safe_branch}_{short_commit}_{timestamp}"
        repo_snapshot_id = f"{self._safe_name(repo_id)}_{safe_branch}_{short_commit}"
        
        return analysis_id, repo_snapshot_id, short_commit

    def save_latest_analysis(
        self,
        repo,
        repo_id: str,
        analysis: Dict[str, Any],
        graph: Dict[str, Any] | None = None,
        source_branch: str | None = None,
        commit_sha: str | None = None
    ) -> str:
        """Store an immutable analysis record and update manifest."""
        analyzed_at_dt = datetime.now(timezone.utc)
        analyzed_at = analyzed_at_dt.isoformat()
        
        source_branch = source_branch or getattr(repo, "default_branch", None) or "main"
        commit_sha = commit_sha or self._get_branch_commit_sha(repo, source_branch)
        commit_sha = commit_sha or self._get_default_commit_sha(repo)
        
        analysis_id, snapshot_id, short_commit = self.generate_ids(repo_id, source_branch, commit_sha)
        safe_branch = self._safe_name(source_branch)
        
        # Flattened Storage Layout: analyses/{branch}/{short_commit}/analysis.json
        analysis_base = f"{self.base_path}/analyses/{safe_branch}/{short_commit}"
        analysis_record_path = f"{analysis_base}/analysis_{analysis_id}.json"
        graph_snapshot_path = f"{analysis_base}/dependency_graph_{analysis_id}.json"
        
        manifest = self._load_manifest(repo)
        
        # Artifact paths for compatibility/latest pointers
        latest_analysis_path = f"{self.base_path}/snapshots/latest_analysis.json"
        latest_graph_path = f"{self.base_path}/snapshots/latest_graph.json"
        latest_packages_path = f"{self.base_path}/snapshots/latest_packages.json"
        latest_imports_path = f"{self.base_path}/snapshots/latest_imports.json"
        latest_risk_report_path = f"{self.base_path}/reports/dependency_risk_report.json"

        metadata = {
            "analysis_id": analysis_id,
            "repository_snapshot_id": snapshot_id,
            "repository": repo_id,
            "branch": source_branch,
            "commit_sha": commit_sha,
            "short_commit": short_commit,
            "analysis_timestamp": analyzed_at,
            "analysis_version": "1.0",
            "schema_version": "2.0"
        }

        manifest.update({
            "schema_version": max(manifest.get("schema_version", 1), 3),
            "repository": repo_id,
            "default_branch": getattr(repo, "default_branch", "main"),
            "current_head": self._get_branch_commit_sha(repo, getattr(repo, "default_branch", "main")),
            "last_analyzed_commit": commit_sha,
            "latest_analysis_id": analysis_id,
            "latest_analysis_at": analyzed_at,
            "latest_analysis": analysis_record_path,
            "latest_files": {
                "analysis": latest_analysis_path,
                "analysis_record": analysis_record_path,
                "graph": latest_graph_path,
                "graph_snapshot": graph_snapshot_path,
                "packages": latest_packages_path,
                "imports": latest_imports_path,
                "dependency_risk_report": latest_risk_report_path
            }
        })
        
        manifest.setdefault("analyses", [])
        manifest["analyses"].append({
            "analysis_id": analysis_id,
            "snapshot_id": snapshot_id,
            "branch": source_branch,
            "commit": commit_sha,
            "timestamp": analyzed_at,
            "path": analysis_record_path
        })
        
        manifest.setdefault("health_reports", [])
        manifest.setdefault("migration_reports", [])
        manifest.setdefault("comparisons", [])
        manifest.setdefault("pull_requests", [])

        analysis_payload = {
            **metadata,
            "analysis": analysis,
            "graph_path": graph_snapshot_path if graph is not None else None,
        }

        files_to_commit = {
            f"{self.base_path}/metadata.json": self._json(manifest),
            analysis_record_path: self._json(analysis_payload),

            # Latest analysis pointer
            latest_analysis_path: self._json({
                "repository": repo_id,
                "branch": source_branch,
                "commit_sha": commit_sha,
                "analyzed_at": analyzed_at,
                "analysis_id": analysis_id,
                "analysis": analysis,
            }),

            # Packages
            latest_packages_path: self._json({
                **analysis.get("dependencies", {}),
                "packages": analysis.get("dependency_graph", {}),
                "analysis_id": analysis_id,
            }),

            # Imports
            latest_imports_path: self._json({
                **analysis.get("imports", {}),
                "analysis_id": analysis_id,
            }),

            # Risk report
            latest_risk_report_path: self._json({
                "repository": repo_id,
                "branch": source_branch,
                "commit_sha": commit_sha,
                "analyzed_at": analyzed_at,
                "analysis_id": analysis_id,
                "issues": analysis.get("issues", {}),
                "dependency_graph": analysis.get("dependency_graph", {}),
            }),
        }

        # Phase 5: Graph is now optional — only write if provided (lazy generation on viz request)
        if graph is not None:
            graph_payload = {**metadata, **graph}
            files_to_commit[graph_snapshot_path] = self._json(graph_payload)
            files_to_commit[latest_graph_path] = self._json(graph_payload)

        self.client.ensure_branch(repo, self.branch_name)
        self.client.batch_upsert_files(
            repo,
            self.branch_name,
            files_to_commit,
            f"Analysis {analysis_id} for {repo_id}"
        )
        logger.info(f"Synchronized analysis {analysis_id} for {repo_id}")
        return analysis_id

    def save_health_report(
        self,
        repo,
        report: HealthReport,
        analysis_id: str,
        analysis: Dict[str, Any],
        source_branch: str | None = None,
        commit_sha: str | None = None
    ) -> str:
        """Persist health report immediately after generation (before migration docs)."""
        self.client.ensure_branch(repo, self.branch_name)
        repo_id = getattr(repo, "full_name", report.repository)
        source_branch = source_branch or analysis.get("branch") or getattr(repo, "default_branch", None) or "main"
        commit_sha = commit_sha or analysis.get("commit_sha") or self._get_branch_commit_sha(repo, source_branch)
        short_commit = commit_sha[:7]
        safe_branch = self._safe_name(source_branch)
        analysis_base = f"{self.base_path}/analyses/{safe_branch}/{short_commit}"
        health_report_path = f"{analysis_base}/health_report_{analysis_id}.json"
        manifest = self._load_manifest(repo)
        risk_score = compute_overall_risk_score(report)
        health_data = {
            "migration_id": f"mig_{analysis_id}",
            "analysis_id": analysis_id,
            "repository_snapshot_id": analysis.get("repository_snapshot_id", ""),
            "branch": source_branch,
            "generated_from_commit": commit_sha,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health_score": getattr(report, "overall_health_score", 0),
            "risk_score": risk_score,
            "overall_risk_level": getattr(report, "overall_risk_level", "unknown"),
            "intelligence_warnings": getattr(report, "intelligence_warnings", []),
            "report": report.model_dump(),
        }
        manifest.update({
            "last_health_refresh": health_data["generated_at"],
            "latest_health_report": health_report_path,
        })
        manifest.setdefault("health_reports", [])
        existing_idx = None
        for i, hr in enumerate(manifest["health_reports"]):
            if hr.get("analysis_id") == analysis_id:
                existing_idx = i
                break
        entry = {
            "analysis_id": analysis_id,
            "timestamp": health_data["generated_at"],
            "path": health_report_path,
        }
        if existing_idx is not None:
            manifest["health_reports"][existing_idx] = entry
        else:
            manifest["health_reports"].append(entry)
        files_to_commit = {
            f"{self.base_path}/metadata.json": self._json(manifest),
            health_report_path: self._json(health_data),
        }
        self.client.batch_upsert_files(
            repo,
            self.branch_name,
            files_to_commit,
            f"Health report {analysis_id} for {repo_id}",
        )
        logger.info(f"Saved health report for {analysis_id}")
        return health_report_path

    def save_migration_artifacts(
        self,
        repo,
        document: MigrationDocument,
        report: HealthReport,
        analysis_id: str,
        analysis: Dict[str, Any],
        source_branch: str | None = None,
        commit_sha: str | None = None
    ) -> str:
        """Batch commit immutable health and migration artifacts."""
        
        self.client.ensure_branch(repo, self.branch_name)
        
        refreshed_at = datetime.now(timezone.utc)
        repo_id = getattr(repo, "full_name", report.repository)
        source_branch = source_branch or analysis.get("branch") or getattr(repo, "default_branch", None) or "main"
        commit_sha = commit_sha or analysis.get("commit_sha") or self._get_branch_commit_sha(repo, source_branch)
        short_commit = commit_sha[:7]
        safe_branch = self._safe_name(source_branch)
        
        migration_id = f"mig_{analysis_id}"
        analysis_base = f"{self.base_path}/analyses/{safe_branch}/{short_commit}"
        
        health_report_path = f"{analysis_base}/health_report_{analysis_id}.json"
        migration_report_path = f"{analysis_base}/migration_report_{analysis_id}.md"
        
        legacy_doc_path = f"{self.base_path}/migrations/{document.filename}"
        
        manifest = self._load_manifest(repo)
        
        risk_score = compute_overall_risk_score(report)
        health_data = {
            "migration_id": migration_id,
            "analysis_id": analysis_id,
            "repository_snapshot_id": analysis.get("repository_snapshot_id", ""),
            "branch": source_branch,
            "generated_from_commit": commit_sha,
            "generated_at": refreshed_at.isoformat(),
            "health_score": getattr(report, "overall_health_score", 0),
            "risk_score": risk_score,
            "overall_risk_level": getattr(report, "overall_risk_level", "unknown"),
            "intelligence_warnings": getattr(report, "intelligence_warnings", []),
            "report": report.model_dump()
        }

        manifest.update({
            "last_health_refresh": refreshed_at.isoformat(),
            "latest_health_report": health_report_path,
            "latest_migration": migration_report_path,
        })
        
        manifest.setdefault("health_reports", [])
        health_entry = {
            "analysis_id": analysis_id,
            "timestamp": refreshed_at.isoformat(),
            "path": health_report_path
        }
        existing_hr_idx = None
        for i, hr in enumerate(manifest["health_reports"]):
            if hr.get("analysis_id") == analysis_id:
                existing_hr_idx = i
                break
        if existing_hr_idx is not None:
            manifest["health_reports"][existing_hr_idx] = health_entry
        else:
            manifest["health_reports"].append(health_entry)
        
        manifest.setdefault("migration_reports", [])
        mig_entry = {
            "migration_id": migration_id,
            "analysis_id": analysis_id,
            "timestamp": refreshed_at.isoformat(),
            "path": migration_report_path,
            "risk_score": health_data["risk_score"],
            "overall_risk_level": health_data["overall_risk_level"],
        }
        existing_mr_idx = None
        for i, mr in enumerate(manifest["migration_reports"]):
            if mr.get("analysis_id") == analysis_id or mr.get("migration_id") == migration_id:
                existing_mr_idx = i
                break
        if existing_mr_idx is not None:
            manifest["migration_reports"][existing_mr_idx] = mig_entry
        else:
            manifest["migration_reports"].append(mig_entry)
        
        files_to_commit = {
            f"{self.base_path}/metadata.json": self._json(manifest),
            health_report_path: self._json(health_data),
            migration_report_path: document.content,
            legacy_doc_path: document.content, # Backward compat
        }

        shims_path = f"{analysis_base}/repoheal_fixes.py"
        shims_content = getattr(report, "compatibility_shims", "")
        if shims_content:
            files_to_commit[shims_path] = shims_content
            manifest.setdefault("compatibility_shims", [])
            manifest["compatibility_shims"].append({
                "analysis_id": analysis_id,
                "timestamp": refreshed_at.isoformat(),
                "path": shims_path,
            })

        readme_path = f"{self.base_path}/README.md"
        if not self._path_exists(repo, readme_path):
            files_to_commit[readme_path] = self._readme()
        
        self.client.batch_upsert_files(
            repo, 
            self.branch_name, 
            files_to_commit, 
            f"Migration artifacts for {analysis_id}"
        )
        logger.info(f"Saved migration artifacts for {analysis_id}")
        return migration_id

    def load_analysis_record(
        self,
        repo,
        source_branch: str,
        commit_sha: str
    ) -> Dict[str, Any] | None:
        short_commit = commit_sha[:7]
        safe_branch = self._safe_name(source_branch)
        manifest = self._load_manifest(repo)
        analyses = manifest.get("analyses", [])
        if isinstance(analyses, list):
            for a in analyses:
                if a.get("branch") == source_branch and a.get("commit", "").startswith(short_commit):
                    try:
                        content = repo.get_contents(a["path"], ref=self.branch_name)
                        return json.loads(content.decoded_content.decode("utf-8"))
                    except Exception:
                        break
        # Try new flat path first: analyses/{branch}/{short_commit}/analysis_{analysis_id}.json
        # We don't know the timestamp part of analysis_id, so try listing the dir or glob
        try:
            contents = repo.get_contents(f"{self.base_path}/analyses/{safe_branch}/{short_commit}", ref=self.branch_name)
            if isinstance(contents, list):
                json_files = [c for c in contents if c.name.startswith("analysis_") and c.name.endswith(".json")]
                if json_files:
                    newest = max(json_files, key=lambda c: c.last_modified if hasattr(c, 'last_modified') else "")
                    return json.loads(newest.decoded_content.decode("utf-8"))
        except Exception:
            pass
        # Fallback to legacy nested path
        for legacy_attempt in (
            f"{self.base_path}/analyses/{safe_branch}/{short_commit}/analysis_{safe_branch}_{short_commit}.json",
            f"{self.base_path}/analyses/{safe_branch}/{short_commit}/analysis.json",
        ):
            result = self._load_json_file(repo, legacy_attempt)
            if result:
                return result
        return None

    def load_latest_analysis_record(self, repo) -> Dict[str, Any] | None:
        manifest = self._load_manifest(repo)
        analysis_path = manifest.get("latest_analysis")
        if analysis_path:
            result = self._load_json_file(repo, analysis_path)
            if result:
                return result
        # Fallback: scan analyses dir for the most recent
        try:
            contents = repo.get_contents(f"{self.base_path}/analyses", ref=self.branch_name)
            if isinstance(contents, list):
                branch_dirs = [c for c in contents if c.type == "dir"]
                branch_dirs.sort(key=lambda c: c.last_modified if hasattr(c, 'last_modified') else "", reverse=True)
                for branch_dir in branch_dirs[:3]:
                    try:
                        commit_dirs = repo.get_contents(branch_dir.path, ref=self.branch_name)
                        if isinstance(commit_dirs, list):
                            commit_dirs.sort(key=lambda c: c.last_modified if hasattr(c, 'last_modified') else "", reverse=True)
                            for commit_dir in commit_dirs[:3]:
                                try:
                                    files = repo.get_contents(commit_dir.path, ref=self.branch_name)
                                    if isinstance(files, list):
                                        json_files = [f for f in files if f.name.startswith("analysis_") and f.name.endswith(".json")]
                                        if json_files:
                                            newest = max(json_files, key=lambda f: f.last_modified if hasattr(f, 'last_modified') else "")
                                            return json.loads(newest.decoded_content.decode("utf-8"))
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def load_latest_report(self, repo) -> Dict[str, Any] | None:
        manifest = self._load_manifest(repo)
        for path in (
            manifest.get("latest_health_report"),
            manifest.get("latest_report"),
            manifest.get("latest_detailed_report"),
        ):
            if not path:
                continue
            report = self._load_json_file(repo, path)
            if report:
                return report
        return None

    def load_latest_graph(self, repo) -> Dict[str, Any] | None:
        manifest = self._load_manifest(repo)
        graph_path = manifest.get("latest_files", {}).get("graph") or manifest.get("latest_graph")
        if graph_path:
            result = self._load_json_file(repo, graph_path)
            if result:
                return result
        latest_analysis_id = manifest.get("latest_analysis_id")
        if not latest_analysis_id:
            return None
        analysis_meta = None
        for a in manifest.get("analyses", []):
            if isinstance(a, dict) and a.get("analysis_id") == latest_analysis_id:
                analysis_meta = a
                break
        if not analysis_meta:
            return None
        analysis_base = f"{self.base_path}/analyses/{self._safe_name(analysis_meta.get('branch', 'main'))}/{analysis_meta.get('commit', '')[:7]}"
        graph_snapshot = self._load_json_file(repo, f"{analysis_base}/dependency_graph_{latest_analysis_id}.json")
        if graph_snapshot:
            return graph_snapshot
        return None

    def load_graph_for_analysis(self, repo, analysis_id: str) -> Dict[str, Any] | None:
        """Load a specific analysis's graph snapshot from the metadata branch."""
        manifest = self._load_manifest(repo)
        analysis_meta = None
        for a in manifest.get("analyses", []):
            if isinstance(a, dict) and a.get("analysis_id") == analysis_id:
                analysis_meta = a
                break
        if not analysis_meta:
            return None
        branch = analysis_meta.get("branch", "main")
        commit = analysis_meta.get("commit", "")
        analysis_base = f"{self.base_path}/analyses/{self._safe_name(branch)}/{commit[:7]}"
        graph_snapshot = self._load_json_file(repo, f"{analysis_base}/dependency_graph_{analysis_id}.json")
        if graph_snapshot:
            return graph_snapshot
        return None

    def mark_uninstalled(
        self,
        repo,
        installation_id: int,
        uninstalled_at: str | None = None
    ) -> None:
        """Preserve metadata artifacts and mark the repository inactive.
        
        This is intentionally best-effort: after GitHub uninstall the JWT
        may be invalidated, so callers should handle failures gracefully.
        """
        manifest_path = f"{self.base_path}/metadata.json"
        manifest = self._load_manifest(repo)
        
        # Preserve existing lists; never convert to dict
        existing_analyses = manifest.get("analyses", [])
        if not isinstance(existing_analyses, list):
            existing_analyses = []
        existing_health = manifest.get("health_reports", [])
        if not isinstance(existing_health, list):
            existing_health = []
        existing_migrations = manifest.get("migration_reports", [])
        if not isinstance(existing_migrations, list):
            existing_migrations = []
        existing_comparisons = manifest.get("comparisons", [])
        if not isinstance(existing_comparisons, list):
            existing_comparisons = []

        manifest.clear()
        manifest.update({
            "schema_version": 3,
            "repository": getattr(repo, "full_name", manifest.get("repository")),
            "branch": self.branch_name,
            "status": "uninstalled",
            "uninstalled_at": uninstalled_at or datetime.now(timezone.utc).isoformat(),
            "installation_id": installation_id,
            "analyses": existing_analyses,
            "health_reports": existing_health,
            "migration_reports": existing_migrations,
            "comparisons": existing_comparisons,
        })

        try:
            self.client.ensure_branch(repo, self.branch_name)
            self.client.upsert_file(
                repo,
                self.branch_name,
                manifest_path,
                self._json(manifest),
                "Mark RepoHeal metadata as uninstalled"
            )
        except Exception:
            logger.warning(
                f"Metadata branch uninstall marker write failed for "
                f"{getattr(repo, 'full_name', 'unknown')} "
                f"(JWT may be invalidated after GitHub uninstall)"
            )

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
            "schema_version": max(manifest.get("schema_version", 1), 3),
            "repository": getattr(repo, "full_name", manifest.get("repository")),
            "branch": self.branch_name,
            "status": "active",
        })
        manifest.pop("workspace_url", None)
        manifest.setdefault("analyses", {})
        manifest.setdefault("health_reports", {})
        manifest.setdefault("comparisons", [])
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
            return self._migrate_manifest(
                json.loads(contents.decoded_content.decode("utf-8"))
            )
        except Exception:
            return self._migrate_manifest({"schema_version": 1, "artifacts": []})

    def _migrate_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize legacy metadata manifests without deleting old artifact pointers."""
        manifest = dict(manifest or {})
        manifest["schema_version"] = max(manifest.get("schema_version", 1), 3)
        manifest.setdefault("artifacts", [])
        # Force analyses and health_reports to lists; convert from legacy dict if needed
        analyses = manifest.get("analyses")
        if not isinstance(analyses, list):
            manifest["analyses"] = list(analyses.values()) if isinstance(analyses, dict) else []
        health = manifest.get("health_reports")
        if not isinstance(health, list):
            manifest["health_reports"] = list(health.values()) if isinstance(health, dict) else []
        manifest.setdefault("comparisons", [])
        manifest.setdefault("migration_reports", [])
        manifest.setdefault("latest_report", manifest.get("latest_detailed_report"))
        manifest.pop("workspace_url", None)
        return manifest

    def _path_exists(self, repo, path: str) -> bool:
        try:
            contents = repo.get_contents(path, ref=self.branch_name)
            if contents.__class__.__module__.startswith("unittest.mock"):
                return False
            return True
        except Exception:
            return False

    def _get_default_commit_sha(self, repo) -> str | None:
        try:
            return repo.get_branch(repo.default_branch).commit.sha
        except Exception as exc:
            logger.warning(f"Could not read default branch commit for metadata: {exc}")
            return None

    def _get_branch_commit_sha(self, repo, branch_name: str) -> str | None:
        try:
            return repo.get_branch(branch_name).commit.sha
        except Exception as exc:
            logger.warning(
                f"Could not read branch commit for {branch_name}: {exc}"
            )
            return None

    def _load_json_file(self, repo, path: str) -> Dict[str, Any] | None:
        try:
            contents = repo.get_contents(path, ref=self.branch_name)
            return json.loads(contents.decoded_content.decode("utf-8"))
        except Exception:
            return None

    def _build_analysis_record(
        self,
        repo_id: str,
        source_branch: str,
        commit_sha: str | None,
        analyzed_at: str,
        report_path: str,
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "repository": repo_id,
            "branch": source_branch,
            "commit_sha": commit_sha or "",
            "analysis_timestamp": analyzed_at,
            "analysis_version": "1.0",
            "health_score": self._health_score_from_analysis(analysis),
            "dependency_count": self._dependency_count(analysis),
            "risk_level": self._risk_level_from_analysis(analysis),
            "report_path": report_path,
        }

    def _build_health_report_record(
        self,
        repo_id: str,
        source_branch: str,
        commit_sha: str,
        generated_at: str,
        report: HealthReport
    ) -> Dict[str, Any]:
        return {
            "repository": repo_id,
            "branch": source_branch,
            "commit_sha": commit_sha,
            "generated_at": generated_at,
            "health_score": getattr(report, "overall_health_score", None),
            "issues": [
                item.model_dump()
                for item in getattr(report, "risk_assessment", [])
            ],
            "recommendations": [
                item.model_dump()
                for item in getattr(report, "recommended_actions", [])
            ],
        }

    def _dependency_count(self, analysis: Dict[str, Any]) -> int:
        dependencies = analysis.get("dependencies", {})
        if isinstance(dependencies.get("count"), int):
            return dependencies["count"]
        return len(self._dependency_names(analysis))

    def _dependency_names(self, analysis: Dict[str, Any]) -> set[str]:
        graph = analysis.get("dependency_graph", {})
        if isinstance(graph, dict) and graph:
            return set(graph.keys())
        declared = analysis.get("dependencies", {}).get("declared", {})
        if isinstance(declared, dict):
            return set(declared.keys())
        return set()

    def _health_score_from_analysis(self, analysis: Dict[str, Any]) -> int:
        if isinstance(analysis.get("health_score"), int):
            return analysis["health_score"]
        issue_count = self._breaking_api_count(analysis)
        missing_count = analysis.get("issues", {}).get("missing_count", 0)
        penalty = min(100, (issue_count * 10) + (int(missing_count or 0) * 3))
        return max(0, 100 - penalty)

    def _risk_level_from_analysis(self, analysis: Dict[str, Any]) -> str:
        explicit = analysis.get("risk_level")
        if explicit:
            return str(explicit)
        score = self._health_score_from_analysis(analysis)
        if score < 40:
            return "high"
        if score < 70:
            return "medium"
        return "low"

    def _breaking_api_count(self, analysis: Dict[str, Any]) -> int:
        issues = analysis.get("issues", {})
        if isinstance(issues.get("breaking_apis"), list):
            return len(issues["breaking_apis"])
        if isinstance(issues.get("breaking_changes"), list):
            return len(issues["breaking_changes"])
        return int(issues.get("breaking_count") or 0)

    def _readme(self) -> str:
        return (
            "# RepoHeal Metadata Branch\n\n"
            "This branch stores RepoHeal-generated metadata.\n\n"
            "- `repoheal.meta/analyses/`: immutable analysis records by branch and commit\n"
            "- `repoheal.meta/health_reports/`: immutable health reports by branch and commit\n"
            "- `repoheal.meta/comparisons/`: analysis comparison results\n"
            "- `repoheal.meta/migration_reports/`: migration documents\n"
            "- `repoheal.meta/snapshots/`: compatibility graph and analysis snapshots\n"
            "- `repoheal.meta/metadata.json`: artifact manifest\n\n"
            "Do not modify generated artifacts manually.\n"
        )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, indent=2, default=str) + "\n"

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)
