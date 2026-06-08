from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.db.database import get_mongo_db
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _build_fernet() -> Fernet | None:
    encryption_key = settings.GITHUB_TOKEN_ENCRYPTION_KEY
    if not encryption_key:
        return None
    return Fernet(encryption_key.encode())


class SessionStore:

    def _encrypt_token(self, github_token: str) -> str:
        fernet = _build_fernet()
        if not fernet:
            logger.warning("GitHub token encryption key is missing; storing raw token")
            return github_token
        return fernet.encrypt(github_token.encode()).decode()

    def _decrypt_token(self, github_token: str) -> str:
        fernet = _build_fernet()
        if not fernet:
            return github_token
        try:
            return fernet.decrypt(github_token.encode()).decode()
        except InvalidToken:
            logger.warning("Stored GitHub token was not encrypted; returning raw value")
            return github_token

    def create_session(
        self,
        session_id: str,
        github_id: int,
        github_login: str,
        github_token: str
    ):
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        stored_github_token = self._encrypt_token(github_token)

        db = get_mongo_db()
        db.sessions.update_one(
            {"session_id": session_id},
            {"$set": {
                "session_id": session_id,
                "github_id": github_id,
                "github_login": github_login,
                "github_token": stored_github_token,
                "created_at": datetime.now(timezone.utc),
                "expires_at": expires_at,
                "timezone": "UTC",
            }},
            upsert=True
        )
        logger.info(f"Session created for {github_login}")

    def update_timezone(self, session_id: str, timezone: str) -> None:
        db = get_mongo_db()
        db.sessions.update_one(
            {"session_id": session_id},
            {"$set": {"timezone": timezone}}
        )

    def get_session(self, session_id: str):
        db = get_mongo_db()
        doc = db.sessions.find_one({"session_id": session_id})

        if not doc:
            return None

        # MongoDB TTL cleanup is eventual (~60s), so double-check expiry
        expires_at = doc.get("expires_at")

        if expires_at:
            # Handle legacy naive datetimes already stored in MongoDB
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at <= datetime.now(timezone.utc):
                self.delete_session(session_id)
                return None
        return {
            "session_id": doc["session_id"],
            "github_id": doc.get("github_id"),
            "github_login": doc.get("github_login"),
            "github_token": self._decrypt_token(doc["github_token"]) if doc.get("github_token") else None,
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "expires_at": doc.get("expires_at").isoformat() if doc.get("expires_at") else None,
            "timezone": doc.get("timezone", "UTC"),
        }

    def delete_session(self, session_id: str):
        db = get_mongo_db()
        db.sessions.delete_one({"session_id": session_id})
        logger.info(f"Session deleted: {session_id}")

    def delete_sessions_for_github_user(self, github_id: int):
        db = get_mongo_db()
        result = db.sessions.delete_many({"github_id": github_id})
        logger.info(f"Deleted {result.deleted_count} prior sessions for GitHub user: {github_id}")

    def cleanup_expired_sessions(self):
        # MongoDB TTL index handles this automatically, but we can force it
        db = get_mongo_db()
        now = datetime.now(timezone.utc)

        # MongoDB sometimes stores datetimes without timezone info.
        # Convert comparison value to naive UTC for maximum compatibility.
        naive_now = now.replace(tzinfo=None)

        result = db.sessions.delete_many({
            "$or": [
                {"expires_at": {"$lte": now}},
                {"expires_at": {"$lte": naive_now}}
            ]
        })
        logger.info(f"Expired session cleanup complete: {result.deleted_count} deleted")


session_store = SessionStore()