from typing import Dict, List, Any
from datetime import datetime, timezone

from app.models.migration_models import (
    CorrelationResult, ImpactReport, RiskAssessment, HealthReport,
    ExecutiveSummary, DependencyEntry, MigrationPath, RecommendedAction
)


def compute_overall_risk_score(report: HealthReport) -> int:
    """Return 0–100 migration risk (higher = riskier). Aggregates across all risks."""
    if getattr(report, "overall_risk_score", None) is not None:
        return int(report.overall_risk_score)
    if report.risk_assessment:
        return _aggregate_risk_scores(report.risk_assessment)
    if report.overall_risk_level == "high":
        return 75
    if report.overall_risk_level == "medium":
        return 50
    return 0


def _aggregate_risk_scores(risks: List[RiskAssessment]) -> int:
    """Combine multiple risk scores into a single 0-100 score.
    Uses max + density bonus so that more risks increase the score.
    """
    if not risks:
        return 0
    max_score = max(r.risk_score for r in risks)
    high_count = sum(1 for r in risks if r.risk_level == "high")
    med_count = sum(1 for r in risks if r.risk_level == "medium")
    density_bonus = min(30, high_count * 5 + med_count * 3)
    return min(100, max_score + density_bonus)


def compute_overall_risk_score_from_inputs(
    risks: List[RiskAssessment],
    deprecated_count: int,
    breaking_count: int,
) -> int:
    if risks:
        return _aggregate_risk_scores(risks)
    if breaking_count:
        return min(100, 60 + breaking_count * 10)
    if deprecated_count:
        return min(100, 35 + deprecated_count * 8)
    return 0


def assessments_had_intelligence(correlation: CorrelationResult) -> bool:
    return any(
        a.status not in ("healthy", "unknown") or a.relationships
        for a in correlation.assessments
    )


def fingerprint_libraries(analysis: Dict[str, Any]) -> bool:
    fingerprints = analysis.get("fingerprints", {})
    return bool(fingerprints)


class HealthReportGenerator:
    def generate(self, correlation: CorrelationResult, impacts: List[ImpactReport], risks: List[RiskAssessment], analysis: Dict[str, Any]) -> HealthReport:
        # Health Score: how healthy is the repo today (0-100)
        overall_health_score = 100
        critical_count = 0
        deprecated_count = sum(1 for a in correlation.assessments if a.status == "deprecated")
        breaking_count = sum(1 for a in correlation.assessments if a.status == "breaking")

        if risks:
            avg_risk = sum(r.risk_score for r in risks) / len(risks)
            overall_health_score = max(0, int(100 - avg_risk))
            critical_count = sum(1 for r in risks if r.risk_level == "high")
        
        # Migration Risk: how risky would upgrading be (0-100)
        migration_risk_score = compute_overall_risk_score_from_inputs(
            risks, deprecated_count, breaking_count
        )
        if migration_risk_score >= 70:
            migration_risk_level = "high"
        elif migration_risk_score >= 40:
            migration_risk_level = "medium"
        else:
            migration_risk_level = "low"
            
        # Keep old fields for backward compat
        overall_risk_score = migration_risk_score
        overall_risk_level = migration_risk_level
            
        _intel_failed = bool(correlation.webtool_errors) and deprecated_count == 0 and breaking_count == 0

        exec_summary = ExecutiveSummary(
            overall_health_score=overall_health_score,
            critical_findings_count=critical_count,
            deprecated_count=-1 if _intel_failed else deprecated_count,
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
                    
        # Recommended Actions (deduplicated by symbol)
        actions = []
        seen_symbols = set()
        sorted_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)
        path_by_symbol = {
            path.symbol: path
            for path in migration_paths
            if path.relation == "deprecated_in_favor_of"
        }
        for r in sorted_risks:
            if r.symbol in seen_symbols:
                continue
            seen_symbols.add(r.symbol)
            priority = "low"
            if r.risk_level == "high":
                priority = "critical"
            elif r.risk_level == "medium":
                priority = "high"
            else:
                priority = "medium"

            migration_path = path_by_symbol.get(r.symbol)
            target = f" with `{migration_path.target}`" if migration_path else ""
            symbol_assessment = next((a for a in correlation.assessments if a.symbol == r.symbol), None)
            action_confidence = symbol_assessment.compute_confidence() if symbol_assessment else None
                
            actions.append(RecommendedAction(
                symbol=r.symbol,
                priority=priority,
                action_type="migrate_api",
                description=(
                    f"Migrate {r.symbol}{target} to avoid potential breakage. "
                    f"Impacted files: {r.factors.affected_file_count}"
                ),
                confidence=action_confidence
            ))
            
        intelligence_warnings = list(correlation.webtool_errors or [])
        if not assessments_had_intelligence(correlation) and fingerprint_libraries(analysis):
            intelligence_warnings.append(
                "Symbol intelligence returned no deprecation data — "
                "version-gap and pattern-based checks were applied as fallback."
            )

        return HealthReport(
            repository=correlation.repository,
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_health_score=overall_health_score,
            overall_risk_score=overall_risk_score,
            overall_risk_level=overall_risk_level,
            migration_risk_score=migration_risk_score,
            migration_risk_level=migration_risk_level,
            intelligence_warnings=intelligence_warnings,
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
        ]
        if report.intelligence_warnings:
            sections.append(self._render_intelligence_warnings(report))
        sections.extend([
            self._render_dependency_inventory(report),
            self._render_symbol_section("Deprecated APIs", report.deprecated_apis),
            self._render_symbol_section("Breaking Changes", report.breaking_changes),
            self._render_migration_paths(report),
            self._render_risk_assessment(report),
            self._render_recommended_actions(report),
        ])
        return "\n\n---\n\n".join(sections) + "\n"

    def _render_intelligence_warnings(self, report: HealthReport) -> str:
        lines = ["## Intelligence Warnings", ""]
        for warning in report.intelligence_warnings:
            lines.append(f"- {warning}")
        return "\n".join(lines)

    def _render_executive_summary(self, report: HealthReport) -> str:
        summary = report.executive_summary
        deprecated_str = "UNKNOWN" if summary.deprecated_count == -1 else str(summary.deprecated_count)
        intel_lines = []
        if report.migration_intelligence_status == "failed":
            intel_lines.extend([
                "",
                "**Migration Intelligence Status**: FAILED",
                f"**Root cause**: {report.intelligence_error or 'Intelligence provider returned no data'}",
                "**Note**: Analysis continues without external intelligence. AST, dependency analysis, risk scoring, and graph generation all complete.",
            ])
        elif report.migration_intelligence_status == "degraded":
            intel_lines.extend([
                "",
                "**Migration Intelligence Status**: DEGRADED",
                f"**Note**: Primary intelligence provider had errors, but local fallback provided data.",
                f"**Error**: {report.intelligence_error or 'Unknown webtool error'}",
            ])
        if report.intelligence_source and report.intelligence_source not in ("unknown", "none"):
            intel_lines.append(f"**Intelligence Source**: {report.intelligence_source}")
        return "\n".join([
            "# Migration Assessment",
            "",
            f"**Repository**: {report.repository}",
            f"**Generated**: {report.generated_at}",
            f"**Overall Health Score**: {report.overall_health_score}/100",
            f"**Migration Risk Score**: {report.migration_risk_score}/100",
            f"**Migration Risk Level**: {report.migration_risk_level.upper()}",
            f"**Migration Intelligence Status**: {report.migration_intelligence_status.upper()}",
            "",
            "## Executive Summary",
            "",
            f"- Critical findings: {summary.critical_findings_count}",
            f"- Deprecated APIs: {deprecated_str}",
            f"- Breaking changes: {summary.breaking_count}",
        ] + intel_lines)

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
            conf = f" (confidence: {action.confidence:.2f})" if isinstance(action.confidence, float) else ""
            lines.append(
                f"- [{action.priority.upper()}] `{action.symbol}`{conf}: "
                f"{action.description}"
            )
        return "\n".join(lines)
