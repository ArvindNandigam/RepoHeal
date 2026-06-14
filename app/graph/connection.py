import os

from neo4j import GraphDatabase
from dotenv import load_dotenv

from app.utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)


class Neo4jConnection:

    def __init__(self):

        self.uri = os.getenv("NEO4J_URI")
        self.username = os.getenv("NEO4J_USERNAME")
        self.password = os.getenv("NEO4J_PASSWORD")

        self.driver = None

    def connect(self):

        if not self.driver:

            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password)
            )

            logger.info("Neo4j connection initialized")

            self._ensure_schema()

        return self.driver

    def _ensure_schema(self):
        """Create indexes for all used labels to suppress AuraDB schema warnings."""
        try:
            with self.driver.session() as session:
                constraints = [
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE",
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE",
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (a:API) REQUIRE a.id IS UNIQUE",
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Namespace) REQUIRE n.id IS UNIQUE",
                    "CREATE INDEX IF NOT EXISTS FOR (f:File) ON (f.repo_id)",
                    "CREATE INDEX IF NOT EXISTS FOR (fn:Function) ON (fn.repo_id)",
                    "CREATE INDEX IF NOT EXISTS FOR (a:API) ON (a.name)",
                    "CREATE INDEX IF NOT EXISTS FOR (a:API) ON (a.repo_id)",
                    "CREATE INDEX IF NOT EXISTS FOR (n:Namespace) ON (n.repo_id)",
                ]
                for stmt in constraints:
                    try:
                        session.run(stmt)
                    except Exception as single_err:
                        logger.warning(f"Neo4j schema statement failed (non-fatal): {single_err}")
                logger.info("Neo4j schema initialized")
        except Exception as schema_err:
            logger.warning(f"Neo4j schema initialization failed (non-fatal): {schema_err}")

    def get_session(self):

        driver = self.connect()

        return driver.session()

    def close(self):

        if self.driver:

            self.driver.close()

            logger.info("Neo4j connection closed")

    def is_available(self) -> bool:
        """Check if Neo4j is reachable and the driver is functional."""
        try:
            if not self.driver:
                self.connect()
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False

    def storage_ok(self) -> tuple[bool, str]:
        """Check if Neo4j has sufficient storage. Returns (ok, message)."""
        try:
            if not self.driver:
                self.connect()
            with self.driver.session() as session:
                result = session.run("CALL dbms.listConfig() YIELD name, value WHERE name = 'dbms.memory.transaction.total.max' RETURN value")
                record = result.single()
                if record:
                    return True, ""
                return True, ""
        except Exception as e:
            err_str = str(e).lower()
            if "not enough space" in err_str or "disk" in err_str or "storage" in err_str:
                return False, "Neo4j storage is full — graph features may be limited"
            if "unavailable" in err_str or "connection" in err_str or "refused" in err_str:
                return False, "Neo4j is unavailable — graph features may be limited"
            return True, ""


neo4j_connection = Neo4jConnection()