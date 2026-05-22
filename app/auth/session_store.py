from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app.graph.connection import (
    neo4j_connection
)

from app.config import settings

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def _build_fernet() -> Fernet | None:

    encryption_key = settings.GITHUB_TOKEN_ENCRYPTION_KEY

    if not encryption_key:
        return None

    return Fernet(encryption_key.encode())


class SessionStore:

    def _encrypt_token(
        self,
        github_token: str
    ) -> str:

        fernet = _build_fernet()

        if not fernet:
            logger.warning(
                "GitHub token encryption key is missing; storing raw token"
            )
            return github_token

        return fernet.encrypt(
            github_token.encode()
        ).decode()

    def _decrypt_token(
        self,
        github_token: str
    ) -> str:

        fernet = _build_fernet()

        if not fernet:
            return github_token

        try:
            return fernet.decrypt(
                github_token.encode()
            ).decode()
        except InvalidToken:
            logger.warning(
                "Stored GitHub token was not encrypted; returning raw value"
            )
            return github_token

    def _is_expired(
        self,
        expires_at: str | None
    ) -> bool:

        if not expires_at:
            return True

        try:
            return datetime.fromisoformat(
                expires_at
            ) <= datetime.utcnow()
        except ValueError:
            return True

    def create_session(
        self,
        session_id: str,
        github_id: int,
        github_login: str,
        github_token: str
    ):

        expires_at = (
            datetime.utcnow()
            + timedelta(days=1)
        ).isoformat()

        stored_github_token = self._encrypt_token(
            github_token
        )

        with neo4j_connection.get_session() as session:

            session.run(
                """
                MERGE (s:Session {
                    session_id: $session_id
                })

                SET
                    s.github_id = $github_id,
                    s.github_login = $github_login,
                    s.github_token = $github_token,
                    s.created_at = $created_at,
                    s.expires_at = $expires_at
                """,
                session_id=session_id,
                github_id=github_id,
                github_login=github_login,
                github_token=stored_github_token,
                created_at=datetime.utcnow().isoformat(),
                expires_at=expires_at
            )

        logger.info(
            f"Session created for "
            f"{github_login}"
        )

    def get_session(
        self,
        session_id: str
    ):

        with neo4j_connection.get_session() as session:

            result = session.run(
                """
                MATCH (s:Session {
                    session_id: $session_id
                })

                RETURN s
                """,
                session_id=session_id
            )

            record = result.single()

            if not record:
                return None

            session_data = dict(record["s"])

            if "github_token" in session_data:
                session_data["github_token"] = self._decrypt_token(
                    session_data["github_token"]
                )

            if self._is_expired(
                session_data.get("expires_at")
            ):

                self.delete_session(
                    session_id
                )

                return None

            return session_data

    def delete_session(
        self,
        session_id: str
    ):

        with neo4j_connection.get_session() as session:

            session.run(
                """
                MATCH (s:Session {
                    session_id: $session_id
                })

                DETACH DELETE s
                """,
                session_id=session_id
            )

        logger.info(
            f"Session deleted: "
            f"{session_id}"
        )

    def delete_sessions_for_github_user(
        self,
        github_id: int
    ):

        with neo4j_connection.get_session() as session:

            session.run(
                """
                MATCH (s:Session {
                    github_id: $github_id
                })

                DETACH DELETE s
                """,
                github_id=github_id
            )

        logger.info(
            f"Deleted prior sessions for GitHub user: {github_id}"
        )

    def cleanup_expired_sessions(self):

        with neo4j_connection.get_session() as session:

            result = session.run(
                """
                MATCH (s:Session)
                WHERE s.expires_at IS NOT NULL
                  AND datetime(s.expires_at) < datetime()
                WITH s
                DETACH DELETE s
                RETURN count(*) AS deleted_count
                """
            )

            record = result.single()

            deleted_count = (
                record["deleted_count"]
                if record
                else 0
            )

        logger.info(
            f"Expired session cleanup complete: {deleted_count} deleted"
        )


session_store = SessionStore()