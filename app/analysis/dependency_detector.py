from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_requirements(repo_path):

    dependencies = {}

    requirements_path = Path(repo_path) / "requirements.txt"

    if not requirements_path.exists():

        logger.warning("No requirements.txt found")

        return dependencies

    with open(requirements_path, "r") as f:

        lines = f.readlines()

    for line in lines:

        line = line.strip()

        if "==" in line:

            package, version = line.split("==")

            dependencies[package] = version

        elif line:

            dependencies[line] = "unknown"

    logger.info(
        f"Detected {len(dependencies)} dependencies"
    )

    return dependencies