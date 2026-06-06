from typing import Dict, List, Any
from datetime import datetime, timezone

from app.models.migration_models import (
    CorrelationResult, ImpactReport, RiskAssessment, HealthReport,
    ExecutiveSummary, DependencyEntry, MigrationPath, RecommendedAction
)

class HealthReportGenerator:
    def generate(self, correlation: CorrelationResult, impacts: List[ImpactReport], risks: List[RiskAssessment], analysis: Dict[str, Any]) -> HealthReport:
        # Calculate Executive Summary metrics
        overall_health_score = 100
        critical_count = 0
        
        if risks:
            avg_risk = sum(r.risk_score for r in risks) / len(risks)
            overall_health_score = max(0, int(100 - avg_risk))
            critical_count = sum(1 for r in risks if r.risk_level == "high")
            
        deprecated_count = sum(1 for a in correlation.assessments if a.status == "deprecated")
        breaking_count = sum(1 for a in correlation.assessments if a.status == "breaking")
        
        if overall_health_score < 40:
            overall_risk_level = "high"
        elif overall_health_score < 70:
            overall_risk_level = "medium"
        else:
            overall_risk_level = "low"
            
        exec_summary = ExecutiveSummary(
            overall_health_score=overall_health_score,
            critical_findings_count=critical_count,
            deprecated_count=deprecated_count,
            breaking_count=breaking_count
        )
        
        # Dependency Inventory
        dependencies = analysis.get("dependency_graph", {})
        inventory = []
        for pkg, info in dependencies.items():
            inventory.append(DependencyEntry(
                name=pkg,
                installed_version=info.get("version", "unknown"),
                latest_version=info.get("latest_version", "unknown"),
                status=info.get("status", "unknown"),
                type=info.get("type", "detected")
            ))
            
        # Deprecated & Breaking API lists
        deprecated_apis = [a for a in correlation.assessments if a.status == "deprecated"]
        breaking_changes = [a for a in correlation.assessments if a.status == "breaking"]
        
        # Migration Paths
        migration_paths = []
        for a in correlation.assessments:
            for rel in a.relationships:
                if rel.target:
                    migration_paths.append(MigrationPath(
                        symbol=a.symbol,
                        target=rel.target,
                        relation=rel.relation,
                        confidence=rel.confidence
                    ))
                    
        # Recommended Actions
        actions = []
        sorted_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)
        for r in sorted_risks:
            priority = "low"
            if r.risk_level == "high":
                priority = "critical"
            elif r.risk_level == "medium":
                priority = "high"
            else:
                priority = "medium"
                
            actions.append(RecommendedAction(
                symbol=r.symbol,
                priority=priority,
                action_type="migrate_api",
                description=f"Migrate {r.symbol} to avoid potential breakage. Impacted files: {r.factors.affected_file_count}"
            ))
            
        return HealthReport(
            repository=correlation.repository,
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_health_score=overall_health_score,
            overall_risk_level=overall_risk_level,
            executive_summary=exec_summary,
            dependency_inventory=inventory,
            deprecated_apis=deprecated_apis,
            breaking_changes=breaking_changes,
            migration_paths=migration_paths,
            risk_assessment=risks,
            recommended_actions=actions
        )

    def to_json(self, report: HealthReport) -> str:
        return report.model_dump_json(indent=2)
