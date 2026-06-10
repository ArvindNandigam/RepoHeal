import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    ENVIRONMENT = os.getenv(
        "ENVIRONMENT",
        "production"
    )

    GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID")
    GITHUB_OAUTH_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

    GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
    GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY")
    GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
    GITHUB_TOKEN_ENCRYPTION_KEY = os.getenv("GITHUB_TOKEN_ENCRYPTION_KEY")

    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

    MONGODB_URI = os.getenv("MONGODB_URI")
    MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "RepoHeal")

    RISK_WEIGHT_AFFECTED_FILES = float(os.getenv("RISK_WEIGHT_AFFECTED_FILES", "0.30"))
    RISK_WEIGHT_BREAKING_SEVERITY = float(os.getenv("RISK_WEIGHT_BREAKING_SEVERITY", "0.25"))
    RISK_WEIGHT_CONFIDENCE = float(os.getenv("RISK_WEIGHT_CONFIDENCE", "0.20"))
    RISK_WEIGHT_VERSION_DISTANCE = float(os.getenv("RISK_WEIGHT_VERSION_DISTANCE", "0.15"))
    RISK_WEIGHT_REPO_SIZE = float(os.getenv("RISK_WEIGHT_REPO_SIZE", "0.10"))

    # Cache governance — Render free tier has ~200MB total disk.
    # Cache must not exceed available free space.
    MAX_CACHE_SIZE_MB = int(os.getenv("MAX_CACHE_SIZE_MB", "50"))
    MAX_ANALYSIS_HISTORY = int(os.getenv("MAX_ANALYSIS_HISTORY", "2"))
    CACHE_RETENTION_DAYS = int(os.getenv("CACHE_RETENTION_DAYS", "7"))

    # Large repository protection — tight limits for Render's 200MB disk.
    # These prevent OOM/crash from repos too large to fit on disk.
    MAX_ZIP_SIZE_MB = int(os.getenv("MAX_ZIP_SIZE_MB", "50"))
    MAX_EXTRACTED_SIZE_MB = int(os.getenv("MAX_EXTRACTED_SIZE_MB", "100"))
    MAX_FILE_COUNT = int(os.getenv("MAX_FILE_COUNT", "5000"))
    MAX_PYTHON_FILE_COUNT = int(os.getenv("MAX_PYTHON_FILE_COUNT", "2000"))
    MIN_FREE_DISK_MB = int(os.getenv("MIN_FREE_DISK_MB", "50"))

    # GridFS: when True, extract to disk instead of MongoDB GridFS (default: False = use GridFS)
    USE_DISK_EXTRACTION = os.getenv("USE_DISK_EXTRACTION", "false").lower() in ("1", "true", "yes")

    # Job recovery
    JOB_ORPHAN_TIMEOUT_MINUTES = int(os.getenv("JOB_ORPHAN_TIMEOUT_MINUTES", "15"))

settings = Settings()


if not settings.JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY missing")

if settings.ENVIRONMENT == "production" and not settings.GITHUB_TOKEN_ENCRYPTION_KEY:
    raise ValueError("GITHUB_TOKEN_ENCRYPTION_KEY missing")

if (
    os.getenv("RENDER") == "true"
    or os.getenv("RENDER_SERVICE_ID")
):
    if settings.ENVIRONMENT != "production":
        raise ValueError(
            "ENVIRONMENT must be set to 'production' on Render"
        )