import uuid
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
from app.models.migration_models import HealthReport

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
    
    async def run(
        self,
        analysis: Dict[str, Any],
        repo_id: str,
        repo: Any,
        analysis_id: str | None = None,
        source_branch: str | None = None,
        commit_sha: str | None = None
    ) -> HealthReport:
        logger.info(f"Starting migration pipeline for {repo_id}")
        
        # 1. Correlate
        correlation = await self.correlator.correlate(analysis, repo_id)
        
        # 2. Impact
        impacts = self.impact_analyzer.analyze(
            analysis.get("semantic_graph", {}),
            correlation.assessments
        )
        
        # 3. Risk
        total_files = len(analysis.get("semantic_graph", {}).get("files", {}))
        risks = self.risk_classifier.classify(correlation.assessments, impacts, total_files)
        
        # 4. Report
        report = self.report_generator.generate(correlation, impacts, risks, analysis)
        
        # 5. Document
        document = self.document_generator.generate(report)
        
        # 6. Metadata Branch
        # Use provided analysis_id or fallback to a short hash if missing
        final_analysis_id = analysis_id or analysis.get("analysis_id") or uuid.uuid4().hex[:10]
        
        self.metadata_manager.save_migration_artifacts(
            repo,
            document,
            report,
            final_analysis_id,
            analysis,
            source_branch=source_branch,
            commit_sha=commit_sha
        )

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
