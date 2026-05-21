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

        return self.driver

    def get_session(self):

        driver = self.connect()

        return driver.session()

    def close(self):

        if self.driver:

            self.driver.close()

            logger.info("Neo4j connection closed")


neo4j_connection = Neo4jConnection()