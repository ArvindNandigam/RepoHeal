from enum import Enum
from app.llm.validator import ValidationResult


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def calculate_overall_confidence(
    migration_confidence: float,
    llm_confidence: float,
    validation: ValidationResult,
    risk_score: float,
    affected_files_count: int,
) -> ConfidenceLevel:
    base = (migration_confidence * 0.3) + (llm_confidence * 0.3)

    if validation.valid and validation.syntax_valid and validation.ast_valid:
        base += 0.2
    else:
        base -= 0.3

    if affected_files_count <= 3:
        base += 0.1
    elif affected_files_count > 10:
        base -= 0.1

    if risk_score > 70:
        base -= 0.15
    elif risk_score <= 30:
        base += 0.1

    if validation.warnings:
        base -= 0.05 * len(validation.warnings)

    base = max(0.0, min(1.0, base))

    if base >= 0.7:
        return ConfidenceLevel.HIGH
    elif base >= 0.4:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW
