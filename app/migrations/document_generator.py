from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.migration_models import HealthReport
from app.reports.health_report import HealthReportGenerator, compute_overall_risk_score


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
        return MigrationDocument(
            filename=filename,
            content=content,
            timestamp=timestamp
        )

    def _render_markdown(self, report: HealthReport) -> str:
        sections = [
            self._render_header(report),
            HealthReportGenerator().to_markdown(report).strip()
        ]
        return "\n\n---\n\n".join(sections) + "\n"

    def _render_header(self, report: HealthReport) -> str:
        confidences = [a.confidence for a in report.recommended_actions if isinstance(a.confidence, float)]
        avg_conf = f"{sum(confidences) / len(confidences):.2f}" if confidences else "N/A"
        risk_score = compute_overall_risk_score(report)
        warning_lines = ""
        if report.intelligence_warnings:
            warning_lines = "\n".join(f"- ⚠ {w}" for w in report.intelligence_warnings) + "\n"
        return (
            "# RepoHeal Migration Document\n\n"
            "**Immutable**: this document is an append-only migration record and "
            "must not be modified after creation.\n"
            f"**Repository**: {report.repository}\n"
            f"**Generated**: {report.generated_at}\n\n"
            "---\n\n"
            "| Metric | Score |\n"
            "|--------|------:|\n"
            f"| **Repository Health** | {report.overall_health_score}/100 |\n"
            f"| **Migration Risk** | {risk_score}/100 ({report.overall_risk_level.upper()}) |\n"
            f"| **Average Confidence** | {avg_conf} |\n"
            f"{warning_lines}"
        )
