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