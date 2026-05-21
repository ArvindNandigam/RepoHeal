import io
import os
import shutil
import zipfile
import requests

from app.utils.logger import get_logger

logger = get_logger(__name__)

TEMP_REPO_DIR = "/tmp/repoheal"


def ensure_temp_directory():

    os.makedirs(TEMP_REPO_DIR, exist_ok=True)


def download_repository_snapshot(repo_owner, repo_name):

    """
    Downloads GitHub repository ZIP snapshot.

    Returns extracted repository path.
    """

    ensure_temp_directory()

    repo_id = f"{repo_owner}/{repo_name}"

    zip_url = (
        f"https://api.github.com/repos/"
        f"{repo_owner}/{repo_name}/zipball"
    )

    logger.info(f"Downloading repository snapshot: {repo_id}")

    response = requests.get(zip_url)

    response.raise_for_status()

    zip_bytes = io.BytesIO(response.content)

    extract_path = os.path.join(
        TEMP_REPO_DIR,
        repo_name
    )

    if os.path.exists(extract_path):
        shutil.rmtree(extract_path)

    with zipfile.ZipFile(zip_bytes, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    extracted_folders = os.listdir(extract_path)

    if not extracted_folders:
        raise Exception("Repository extraction failed")

    final_repo_path = os.path.join(
        extract_path,
        extracted_folders[0]
    )

    logger.info(f"Repository extracted: {final_repo_path}")

    return final_repo_path


def cleanup_repository(repo_path):

    """
    Deletes temporary repository snapshot.
    """

    try:

        root_dir = os.path.dirname(
            os.path.dirname(repo_path)
        )

        if os.path.exists(root_dir):

            shutil.rmtree(root_dir)

            logger.info(f"Cleaned temporary repo: {root_dir}")

    except Exception as e:

        logger.error(f"Cleanup failed: {e}")