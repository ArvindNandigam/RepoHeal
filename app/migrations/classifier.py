from enum import Enum


class MigrationClass(str, Enum):
    SAFE_AST = "safe_ast"
    LLM_CANDIDATE = "llm_candidate"
    MANUAL_REQUIRED = "manual_required"


_SAFE_AST_KEYWORDS = {"rewrite_import", "rename_symbol", "update_api_signature"}
_LLM_CANDIDATE_KEYWORDS = {
    "framework", "upgrade", "migrate", "architectural", "pattern",
    "deprecation", "replacement", "conversion", "refactor",
}
_SAFE_AST_LIBRARIES: set[str] = set()


def classify_recommendation(action_type: str, description: str, library: str, confidence: float) -> MigrationClass:
    desc_lower = description.lower()

    if action_type in _SAFE_AST_KEYWORDS or library in _SAFE_AST_LIBRARIES:
        return MigrationClass.SAFE_AST

    if any(kw in desc_lower for kw in _LLM_CANDIDATE_KEYWORDS):
        return MigrationClass.LLM_CANDIDATE

    if action_type in {"rewrite_import", "rename_symbol", "update_api_signature"}:
        return MigrationClass.SAFE_AST

    if confidence < 0.5:
        return MigrationClass.MANUAL_REQUIRED

    return MigrationClass.LLM_CANDIDATE


def safe_ast_transform_for(action_type: str) -> str | None:
    mapping = {
        "rewrite_import": "ast_transforms.rewrite_import",
        "rename_symbol": "ast_transforms.rename_symbol",
        "update_api_signature": "ast_transforms.update_api_signature",
    }
    return mapping.get(action_type)
