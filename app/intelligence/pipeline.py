import uuid
from datetime import datetime, timezone
from typing import Dict, Any

from app.intelligence.providers import IntelligenceProvider
from app.intelligence.correlator import MigrationCorrelator
from app.analysis.impact_analyzer import ImpactAnalyzer
from app.analysis.risk_classifier import RiskClassifier
from app.reports.health_report import HealthReportGenerator
from app.migrations.document_generator import MigrationDocumentGenerator
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.github.changes_branch import ChangesBranchManager
from app.models.migration_models import HealthReport, CorrelationResult

from app.utils.logger import get_logger

logger = get_logger(__name__)

class MigrationPipeline:
    def __init__(self, intelligence_provider: IntelligenceProvider, github_client: RepoHealGitHubClient):
        self.correlator = MigrationCorrelator(intelligence_provider)
        self.impact_analyzer = ImpactAnalyzer()
        self.risk_classifier = RiskClassifier()
        self.report_generator = HealthReportGenerator()
        self.document_generator = MigrationDocumentGenerator()
        self.metadata_manager = MetadataBranchManager(github_client)
        self.changes_manager = ChangesBranchManager(github_client)
        self.cancel_check = None

    def _check_cancelled(self):
        from app.intelligence.webtool_client import WebtoolClient
        check = self.cancel_check or WebtoolClient.cancel_check
        if check and check():
            raise RuntimeError("Operation cancelled")
    
    async def run(
        self,
        analysis: Dict[str, Any],
        repo_id: str,
        repo: Any,
        analysis_id: str | None = None,
        source_branch: str | None = None,
        commit_sha: str | None = None,
        progress_callback: callable = None,
    ) -> HealthReport:
        logger.info(f"Starting migration pipeline for {repo_id}")

        def _report_progress(step: int, total_steps: int, msg: str):
            if progress_callback:
                progress_callback(step, total_steps, msg)
        
        total_steps = 6

        # --- Diagnostics ---
        fingerprints = analysis.get("fingerprints", {})
        dep_graph = analysis.get("dependency_graph", {})
        fp_count = len(fingerprints)
        dep_count = len(dep_graph)
        symbol_count = sum(len(fp.get("symbols", [])) for fp in fingerprints.values())
        logger.info(
            f"[DIAG] Fingerprints: {fp_count} libs, {symbol_count} symbols | "
            f"Dependencies: {dep_count} packages"
        )
        
        # 1. Correlate
        _report_progress(1, total_steps, "Querying Restricted Webtool for API intelligence")
        try:
            correlation = await self.correlator.correlate(analysis, repo_id)
        except Exception as e:
            logger.error(f"Intelligence correlation crashed: {e}", exc_info=True)
            correlation = CorrelationResult(
                repository=repo_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_symbols=0,
                assessments=[],
                libraries_checked=0,
                webtool_errors=[str(e)],
                intelligence_source="none",
            )
        self._check_cancelled()

        intelligence_status = "success"
        intelligence_error = ""
        intelligence_source = correlation.intelligence_source or "unknown"
        webtool_errors = correlation.webtool_errors or []
        has_actionable = any(
            a.status in ("deprecated", "at_risk", "breaking")
            for a in correlation.assessments
        )
        if webtool_errors:
            intelligence_error = webtool_errors[0] if webtool_errors else "Unknown intelligence error"
            if has_actionable:
                intelligence_status = "degraded"
                intelligence_source = "local_kb"
                logger.warning(
                    f"[DIAG] Intelligence DEGRADED — webtool errors ({len(webtool_errors)}) "
                    f"but local fallback provided data. First error: {intelligence_error}"
                )
            else:
                intelligence_status = "failed"
                intelligence_source = "none"
                logger.warning(
                    f"[DIAG] Intelligence FAILED — errors: {len(webtool_errors)} | "
                    f"first: {intelligence_error}"
                )
        has_deprecated = any(a.status == "deprecated" for a in correlation.assessments)
        if not has_deprecated and not webtool_errors:
            logger.info("[DIAG] Intelligence returned 0 deprecated symbols (all healthy)")
        elif not has_deprecated and webtool_errors and not has_actionable:
            logger.warning("[DIAG] Intelligence failed — deprecated count forced to UNKNOWN")
        
        logger.info(
            f"[DIAG] Correlation: {correlation.libraries_checked} libs, "
            f"{correlation.total_symbols} symbols, "
            f"{len(correlation.assessments)} assessments, "
            f"{len(webtool_errors)} errors"
        )
        
        # 2. Impact
        _report_progress(2, total_steps, "Analyzing impact on files and functions")
        try:
            impacts = self.impact_analyzer.analyze(
                analysis.get("semantic_graph", {}),
                correlation.assessments
            )
        except Exception as e:
            logger.error(f"Impact analysis failed (continuing): {e}")
            impacts = {"affected_files": [], "affected_functions": [], "call_chain_details": []}
        self._check_cancelled()
        
        # 3. Risk
        _report_progress(3, total_steps, "Classifying migration risk")
        try:
            total_files = len(analysis.get("semantic_graph", {}).get("files", {}))
            risks = self.risk_classifier.classify(correlation.assessments, impacts, total_files)
        except Exception as e:
            logger.error(f"Risk classification failed (continuing): {e}")
            risks = []
        self._check_cancelled()
        
        # 4. Report
        _report_progress(4, total_steps, "Generating health report")
        report = self.report_generator.generate(correlation, impacts, risks, analysis)
        report.migration_intelligence_status = intelligence_status
        report.intelligence_error = intelligence_error
        report.intelligence_source = intelligence_source
        self._check_cancelled()

        # 4b. Persist health report immediately (before migration docs),
        #     so it's available even if the rest of the pipeline fails.
        try:
            early_aid = analysis_id or analysis.get("analysis_id") or uuid.uuid4().hex[:10]
            self.metadata_manager.save_health_report(
                repo,
                report,
                early_aid,
                analysis,
                source_branch=source_branch,
                commit_sha=commit_sha,
            )
            logger.info(f"Health report persisted early for {repo_id}")
        except Exception as hr_err:
            logger.warning(f"Early health report save failed (non-fatal): {hr_err}")

        # 5. Document
        _report_progress(5, total_steps, "Generating migration document and compatibility shims")
        try:
            document = self.document_generator.generate(report)
        except Exception as e:
            logger.error(f"Migration document generation failed (continuing): {e}")
            document = {"migration_document": "", "summary": {}}
        self._check_cancelled()
        
        # 5b. Compatibility shims for deprecated APIs with known replacements
        try:
            from app.migrations.compatibility_shims import generate_shims
            shims_code = generate_shims(report, analysis)
            if shims_code:
                logger.info("Generated compatibility shims for deprecated APIs")
                report.compatibility_shims = shims_code
        except Exception as shim_err:
            logger.warning("Compatibility shim generation failed: %s", shim_err)
        
        # 6. Metadata Branch
        _report_progress(6, total_steps, "Saving artifacts to repoheal.meta branch")
        final_analysis_id = analysis_id or analysis.get("analysis_id") or uuid.uuid4().hex[:10]
        try:
            self.metadata_manager.save_migration_artifacts(
                repo,
                document,
                report,
                final_analysis_id,
                analysis,
                source_branch=source_branch,
                commit_sha=commit_sha
            )
        except Exception as e:
            logger.error(f"Metadata branch save failed (non-fatal): {e}")

        # Record migration and remediation metrics
        from app.worker.metrics import record_migration_metrics, record_dependency_intelligence, record_impact_analysis
        migration_candidates = len(report.recommended_actions) if hasattr(report, 'recommended_actions') else 0
        record_migration_metrics(reports=1, simulations=0, auto_fixes=migration_candidates)

        # dependency intelligence from health report
        dep_inventory = report.dependency_inventory if hasattr(report, 'dependency_inventory') else []
        deprecated_count = len(report.deprecated_apis) if hasattr(report, 'deprecated_apis') else 0
        breaking_count = len(report.breaking_changes) if hasattr(report, 'breaking_changes') else 0
        record_dependency_intelligence(
            deps_detected=len(dep_inventory),
            unique_packages=len(set(d.name for d in dep_inventory if hasattr(d, 'name'))),
            deprecated_apis=deprecated_count,
            breaking_apis=breaking_count,
            migration_candidates=migration_candidates
        )

        affected_files = len(impacts.get("affected_files", [])) if isinstance(impacts, dict) else 0
        affected_funcs = len(impacts.get("affected_functions", [])) if isinstance(impacts, dict) else 0
        chains = len(impacts.get("call_chain_details", [])) if isinstance(impacts, dict) else 0
        record_impact_analysis(affected_files, affected_funcs, chains)
        
        logger.info(f"Completed migration pipeline for {repo_id}")
        return report
