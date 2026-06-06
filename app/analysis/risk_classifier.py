from typing import List, Dict

from app.config import settings
from app.models.migration_models import (
    SymbolAssessment, ImpactReport, RiskAssessment, RiskFactors
)

class RiskClassifier:
    def classify(self, assessments: List[SymbolAssessment], impact_reports: List[ImpactReport], total_files: int) -> List[RiskAssessment]:
        impact_map = {r.symbol: r for r in impact_reports}
        results = []
        
        for assessment in assessments:
            if assessment.status in ("healthy", "unknown"):
                continue
                
            impact = impact_map.get(assessment.symbol)
            if not impact:
                continue
                
            affected_file_count = len(impact.affected_files)
            
            # 1. Affected Files Score (0-100)
            # if >20% of files are affected, that's max score (100)
            files_score = min(100.0, (affected_file_count / max(1, total_files)) * 500.0)
            
            # 2. Breaking Severity Score
            severity = "none"
            severity_score = 0.0
            if assessment.status == "breaking":
                severity = "high"
                severity_score = 100.0
            elif assessment.status == "at_risk":
                severity = "medium"
                severity_score = 66.0
            elif assessment.status == "deprecated":
                severity = "low"
                severity_score = 33.0
                
            # 3. Confidence Score (Lower confidence = higher risk)
            max_conf = 0.0
            for rel in assessment.relationships:
                if rel.confidence is not None:
                    max_conf = max(max_conf, rel.confidence)
                elif rel.status == "verified":
                    max_conf = 1.0
            
            conf_score = (1.0 - max_conf) * 100.0
            
            # 4. Version Distance Score
            vd_score = 0.0
            if assessment.version_distance:
                vd_score = min(100.0, float(assessment.version_distance.major_diff * 33 + assessment.version_distance.minor_diff * 10))
                
            # 5. Repo Size Score (Larger repos = harder to migrate = higher risk)
            size_score = min(100.0, float(total_files / 10.0))
            
            weighted_score = (
                files_score * settings.RISK_WEIGHT_AFFECTED_FILES +
                severity_score * settings.RISK_WEIGHT_BREAKING_SEVERITY +
                conf_score * settings.RISK_WEIGHT_CONFIDENCE +
                vd_score * settings.RISK_WEIGHT_VERSION_DISTANCE +
                size_score * settings.RISK_WEIGHT_REPO_SIZE
            )
            
            final_score = int(min(100, max(0, weighted_score)))
            risk_level = self._score_to_level(final_score)
            
            factors = RiskFactors(
                affected_file_count=affected_file_count,
                affected_file_percentage=impact.impact_breadth,
                breaking_severity=severity,
                replacement_confidence=max_conf,
                version_distance_score=vd_score,
                repo_file_count=total_files
            )
            
            results.append(RiskAssessment(
                symbol=assessment.symbol,
                risk_score=final_score,
                risk_level=risk_level,
                factors=factors
            ))
            
        return results

    def _score_to_level(self, score: int) -> str:
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"
