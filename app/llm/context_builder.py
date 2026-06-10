from typing import Any


class MigrationContext:
    def __init__(
        self,
        repository: str,
        library: str,
        current_version: str,
        target_version: str,
        symbol: str,
        replacement: str,
        affected_files: list[dict[str, Any]],
        confidence: float,
        risk_score: float,
        recommendation: dict[str, Any],
    ):
        self.repository = repository
        self.library = library
        self.current_version = current_version
        self.target_version = target_version
        self.symbol = symbol
        self.replacement = replacement
        self.affected_files = affected_files
        self.confidence = confidence
        self.risk_score = risk_score
        self.recommendation = recommendation

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "library": self.library,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "symbol": self.symbol,
            "replacement": self.replacement,
            "affected_files": [
                {
                    "path": f["path"],
                    "code": f["content"][:2000] if len(f.get("content", "")) > 2000 else f.get("content", ""),
                    "start_line": f.get("start_line", 1),
                    "end_line": f.get("end_line", len(f.get("content", "").splitlines())),
                }
                for f in self.affected_files
            ],
            "confidence": self.confidence,
            "risk_score": self.risk_score,
        }

    @classmethod
    def from_recommendation(
        cls,
        repo_id: str,
        recommendation: dict[str, Any],
        analysis: dict[str, Any],
        affected_files_content: list[dict[str, Any]],
    ) -> "MigrationContext":
        return cls(
            repository=repo_id,
            library=recommendation.get("library", ""),
            current_version=recommendation.get("installed_version", ""),
            target_version=recommendation.get("latest_version", ""),
            symbol=recommendation.get("symbol", ""),
            replacement=recommendation.get("replacement", ""),
            affected_files=affected_files_content,
            confidence=recommendation.get("confidence", 0.0),
            risk_score=recommendation.get("risk_score", 50),
            recommendation=recommendation,
        )


def build_migration_context(
    repo_id: str,
    recommendation: dict[str, Any],
    analysis: dict[str, Any],
    file_contents_cache: dict[str, str] | None = None,
) -> MigrationContext:
    symbol = recommendation.get("symbol", "")
    sem_graph = analysis.get("semantic_graph", {})
    files = sem_graph.get("files", {})
    affected_files_content: list[dict[str, Any]] = []
    files_seen = 0

    for fpath, finfo in files.items():
        if files_seen >= 5:
            break
        if file_contents_cache and fpath in file_contents_cache:
            content = file_contents_cache[fpath]
            affected_files_content.append({
                "path": fpath,
                "content": content,
                "start_line": 1,
                "end_line": len(content.splitlines()),
            })
            files_seen += 1

    if not affected_files_content:
        for fpath, finfo in files.items():
            if files_seen >= 5:
                break
            content = finfo.get("source", "")
            if not content:
                continue
            affected_files_content.append({
                "path": fpath,
                "content": content,
                "start_line": 1,
                "end_line": len(content.splitlines()),
            })
            files_seen += 1

    return MigrationContext.from_recommendation(repo_id, recommendation, analysis, affected_files_content)
