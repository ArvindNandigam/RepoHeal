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
    
    async def run(self, analysis: Dict[str, Any], repo_id: str, repo: Any) -> HealthReport:
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
        snapshot_id = uuid.uuid4().hex[:10]
        self.metadata_manager.save_migration_artifacts(repo, document, report, snapshot_id, analysis)
        
        logger.info(f"Completed migration pipeline for {repo_id}")
        return report
