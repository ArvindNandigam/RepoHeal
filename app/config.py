import os

from dotenv import load_dotenv


load_dotenv()


class Settings:

	GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
	GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY")
	GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

	NEO4J_URI = os.getenv("NEO4J_URI")
	NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
	NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


settings = Settings()
