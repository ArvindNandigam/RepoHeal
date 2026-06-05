from fastapi import Request
from fastapi.responses import JSONResponse

class RepoHealError(Exception):
    def __init__(self, message: str, status_code: int = 500, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}

class AuthenticationError(RepoHealError):
    def __init__(self, message: str = "Authentication failed", details: dict = None):
        super().__init__(message, status_code=401, details=details)

class AuthorizationError(RepoHealError):
    def __init__(self, message: str = "Authorization failed", details: dict = None):
        super().__init__(message, status_code=403, details=details)

class RepositoryNotFoundError(RepoHealError):
    def __init__(self, message: str = "Repository not found", details: dict = None):
        super().__init__(message, status_code=404, details=details)

class AnalysisError(RepoHealError):
    def __init__(self, message: str = "Analysis failed", details: dict = None):
        super().__init__(message, status_code=500, details=details)

class GraphError(RepoHealError):
    def __init__(self, message: str = "Graph operation failed", details: dict = None):
        super().__init__(message, status_code=500, details=details)

class ExternalServiceError(RepoHealError):
    def __init__(self, message: str = "External service failed", details: dict = None):
        super().__init__(message, status_code=502, details=details)

class RateLimitError(RepoHealError):
    def __init__(self, message: str = "Rate limit exceeded", details: dict = None):
        super().__init__(message, status_code=429, details=details)

async def repoheal_error_handler(request: Request, exc: RepoHealError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": exc.__class__.__name__,
                "message": exc.message,
                "details": exc.details
            }
        }
    )
