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
        breaking_changes = [a for a in correlation.assessments if a.status in ("breaking", "at_risk")]
        
        # Migration Paths
        migration_paths = []
        seen_paths = set()
        for a in correlation.assessments:
            for rel in a.relationships:
                if rel.target:
                    key = (a.symbol, rel.target, rel.relation)
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    migration_paths.append(MigrationPath(
                        symbol=a.symbol,
                        target=rel.target,
                        relation=rel.relation,
                        confidence=rel.confidence
                    ))
                    
        # Recommended Actions
        actions = []
        sorted_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)
        path_by_symbol = {
            path.symbol: path
            for path in migration_paths
            if path.relation == "deprecated_in_favor_of"
        }
        for r in sorted_risks:
            priority = "low"
            if r.risk_level == "high":
                priority = "critical"
            elif r.risk_level == "medium":
                priority = "high"
            else:
                priority = "medium"

            migration_path = path_by_symbol.get(r.symbol)
            target = f" with `{migration_path.target}`" if migration_path else ""
                
            actions.append(RecommendedAction(
                symbol=r.symbol,
                priority=priority,
                action_type="migrate_api",
                description=(
                    f"Migrate {r.symbol}{target} to avoid potential breakage. "
                    f"Impacted files: {r.factors.affected_file_count}"
                )
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
            impact_reports=impacts,
            risk_assessment=risks,
            recommended_actions=actions
        )

    def to_json(self, report: HealthReport) -> str:
        return report.model_dump_json(indent=2)

    def to_markdown(self, report: HealthReport) -> str:
        sections = [
            self._render_executive_summary(report),
            self._render_dependency_inventory(report),
            self._render_symbol_section("Deprecated APIs", report.deprecated_apis),
            self._render_symbol_section("Breaking Changes", report.breaking_changes),
            self._render_migration_paths(report),
            self._render_risk_assessment(report),
            self._render_recommended_actions(report),
        ]
        return "\n\n---\n\n".join(sections) + "\n"

    def _render_executive_summary(self, report: HealthReport) -> str:
        summary = report.executive_summary
        return "\n".join([
            "# Migration Health Report",
            "",
            f"**Repository**: {report.repository}",
            f"**Generated**: {report.generated_at}",
            f"**Overall Health Score**: {report.overall_health_score}/100",
            f"**Overall Risk Level**: {report.overall_risk_level.upper()}",
            "",
            "## Executive Summary",
            "",
            f"- Critical findings: {summary.critical_findings_count}",
            f"- Deprecated APIs: {summary.deprecated_count}",
            f"- Breaking changes: {summary.breaking_count}",
        ])

    def _render_dependency_inventory(self, report: HealthReport) -> str:
        lines = ["## Dependency Inventory"]
        if not report.dependency_inventory:
            return "\n".join(lines + ["", "No dependencies found."])

        lines.extend(["", "| Dependency | Installed | Latest | Status | Type |", "| --- | --- | --- | --- | --- |"])
        for dependency in report.dependency_inventory:
            lines.append(
                "| "
                f"{dependency.name} | {dependency.installed_version} | "
                f"{dependency.latest_version} | {dependency.status} | "
                f"{dependency.type} |"
            )
        return "\n".join(lines)

    def _render_symbol_section(self, title: str, assessments: List) -> str:
        lines = [f"## {title}"]
        if not assessments:
            return "\n".join(lines + ["", "None found."])

        for assessment in assessments:
            lines.extend([
                "",
                f"### {assessment.symbol}",
                f"- Library: {assessment.library}",
                f"- Installed version: {assessment.installed_version}",
                f"- Latest version: {assessment.latest_version}",
                f"- Status: {assessment.status}",
            ])
            if assessment.files_using:
                lines.append(f"- Files using: {', '.join(assessment.files_using)}")
            if assessment.functions_using:
                lines.append(f"- Functions using: {', '.join(assessment.functions_using)}")
            if assessment.version_distance:
                distance = assessment.version_distance
                if distance.deprecated_in:
                    lines.append(f"- Deprecated in: {distance.deprecated_in}")
                if distance.removed_in:
                    lines.append(f"- Removed in: {distance.removed_in}")
            evidence = [
                link
                for relationship in assessment.relationships
                for link in relationship.evidence_links
            ]
            if evidence:
                lines.append(f"- Evidence: {', '.join(dict.fromkeys(evidence))}")

        return "\n".join(lines)

    def _render_migration_paths(self, report: HealthReport) -> str:
        lines = ["## Migration Paths"]
        if not report.migration_paths:
            return "\n".join(lines + ["", "No migration paths identified."])

        for path in report.migration_paths:
            confidence = (
                f"{path.confidence:.2f}"
                if isinstance(path.confidence, float)
                else "unknown"
            )
            lines.append(
                f"- `{path.symbol}` -> `{path.target}` "
                f"({path.relation}, confidence: {confidence})"
            )
        return "\n".join(lines)

    def _render_risk_assessment(self, report: HealthReport) -> str:
        lines = ["## Risk Assessment"]
        if not report.risk_assessment:
            return "\n".join(lines + ["", "No risks identified."])

        impact_by_symbol = {
            impact.symbol: impact
            for impact in report.impact_reports
        }
        for risk in report.risk_assessment:
            impact = impact_by_symbol.get(risk.symbol)
            lines.extend([
                "",
                f"### {risk.symbol}",
                f"- Risk score: {risk.risk_score}/100 ({risk.risk_level})",
                f"- Affected files: {risk.factors.affected_file_count} ({risk.factors.affected_file_percentage:.1f}%)",
                f"- Breaking severity: {risk.factors.breaking_severity}",
                f"- Replacement confidence: {risk.factors.replacement_confidence:.2f}",
            ])
            if impact:
                lines.append(f"- Call chain depth: {impact.impact_depth}")
                if impact.affected_classes:
                    lines.append(f"- Affected classes: {', '.join(impact.affected_classes)}")

        return "\n".join(lines)

    def _render_recommended_actions(self, report: HealthReport) -> str:
        lines = ["## Recommended Actions"]
        if not report.recommended_actions:
            return "\n".join(lines + ["", "No actions recommended."])

        for action in report.recommended_actions:
            lines.append(
                f"- [{action.priority.upper()}] `{action.symbol}`: "
                f"{action.description}"
            )
        return "\n".join(lines)
