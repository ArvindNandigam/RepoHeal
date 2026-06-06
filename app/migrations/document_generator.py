import os
from datetime import datetime, timezone
from dataclasses import dataclass

from app.models.migration_models import HealthReport, ExecutiveSummary

@dataclass
class MigrationDocument:
    filename: str
    content: str
    timestamp: str

class MigrationDocumentGenerator:
    def generate(self, health_report: HealthReport) -> MigrationDocument:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"migration_{timestamp}.md"
        content = self._render_markdown(health_report)
        return MigrationDocument(filename=filename, content=content, timestamp=timestamp)
        
    def _render_markdown(self, report: HealthReport) -> str:
        sections = [
            self._render_header(report),
            self._render_executive_summary(report.executive_summary),
            self._render_deprecated_apis(report.deprecated_apis),
            self._render_breaking_changes(report.breaking_changes),
            self._render_migration_paths(report.migration_paths),
            self._render_risk_assessment(report.risk_assessment),
            self._render_recommended_actions(report.recommended_actions)
        ]
        return "\n\n---\n\n".join(sections)
        
    def _render_header(self, report: HealthReport) -> str:
        return f"# RepoHeal Migration Document\n\n**Repository**: {report.repository}\n**Generated**: {report.generated_at}\n**Overall Risk Level**: {report.overall_risk_level.upper()}\n**Health Score**: {report.overall_health_score}/100"

    def _render_executive_summary(self, summary: ExecutiveSummary) -> str:
        return f"## Executive Summary\n\n- **Health Score**: {summary.overall_health_score}\n- **Critical Findings**: {summary.critical_findings_count}\n- **Deprecated APIs**: {summary.deprecated_count}\n- **Breaking Changes**: {summary.breaking_count}"
        
    def _render_deprecated_apis(self, apis) -> str:
        if not apis:
            return "## Deprecated APIs\n\nNone found."
        lines = ["## Deprecated APIs\n"]
        for a in apis:
            lines.append(f"- `{a.symbol}` (Library: {a.library}, Installed: {a.installed_version}, Latest: {a.latest_version})")
        return "\n".join(lines)
        
    def _render_breaking_changes(self, apis) -> str:
        if not apis:
            return "## Breaking Changes\n\nNone found."
        lines = ["## Breaking Changes\n"]
        for a in apis:
            lines.append(f"- `{a.symbol}` (Library: {a.library}, Installed: {a.installed_version}, Latest: {a.latest_version})")
        return "\n".join(lines)
        
    def _render_migration_paths(self, paths) -> str:
        if not paths:
            return "## Migration Paths\n\nNo migration paths identified."
        lines = ["## Migration Paths\n"]
        for p in paths:
            lines.append(f"- **{p.symbol}** → `{p.target}` ({p.relation}) [Confidence: {p.confidence or 'Unknown'}]")
        return "\n".join(lines)
        
    def _render_risk_assessment(self, risks) -> str:
        if not risks:
            return "## Risk Assessment\n\nNo risks identified."
        lines = ["## Risk Assessment\n"]
        for r in risks:
            lines.append(f"### {r.symbol}\n- **Risk Score**: {r.risk_score} ({r.risk_level.upper()})\n- **Affected Files**: {r.factors.affected_file_count} ({(r.factors.affected_file_percentage):.1f}%)\n- **Breaking Severity**: {r.factors.breaking_severity}\n- **Replacement Confidence**: {r.factors.replacement_confidence}")
        return "\n".join(lines)
        
    def _render_recommended_actions(self, actions) -> str:
        if not actions:
            return "## Recommended Actions\n\nNo actions recommended."
        lines = ["## Recommended Actions\n"]
        for a in actions:
            lines.append(f"- **[{a.priority.upper()}]** `{a.symbol}`: {a.description}")
        return "\n".join(lines)
