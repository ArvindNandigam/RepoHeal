"""
RepoHeal Maintenance Worker

Run manually or via cron to clean up expired sessions and stale jobs.
On Render free tier, background tasks run in-process via FastAPI BackgroundTasks.
This script is only needed for periodic maintenance.

Usage:
    python worker.py
"""
from app.auth.session_store import session_store
from app.utils.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("Running maintenance tasks...")
    session_store.cleanup_expired_sessions()
    logger.info("Maintenance complete.")
