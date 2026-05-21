import io
import os
import shutil
import zipfile

import requests

from app.github.auth import (
    get_installation_token
)

from app.github.installations import (
    get_repository_installation
)

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)

TEMP_REPO_DIR = "/tmp/repoheal"


def ensure_temp_directory():

    os.makedirs(
        TEMP_REPO_DIR,
        exist_ok=True
    )


def get_repository_archive_url(
    repo_owner,
    repo_name
):

    return (
        f"https://api.github.com/repos/"
        f"{repo_owner}/{repo_name}/zipball"
    )


def download_repository_snapshot(
    repo_owner,
    repo_name
):

    """
    Downloads repository ZIP snapshot
    ONLY if RepoHeal GitHub App is installed.

    Uses installation-scoped access token.
    """

    ensure_temp_directory()

    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(
        f"Preparing repository download: "
        f"{repo_id}"
    )

    # Verify app installation
    installation = (
        get_repository_installation(
            repo_owner,
            repo_name
        )
    )

    if not installation:

        logger.warning(
            f"RepoHeal not installed on "
            f"{repo_id}"
        )

        raise PermissionError(
            "RepoHeal is not installed "
            "on this repository"
        )

    installation_id = installation["id"]

    logger.info(
        f"Using installation ID: "
        f"{installation_id}"
    )

    # Generate installation token
    access_token = (
        get_installation_token(
            installation_id
        )
    )

    zip_url = get_repository_archive_url(
        repo_owner,
        repo_name
    )

    headers = {
        "Authorization": (
            f"token {access_token}"
        ),
        "Accept": (
            "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version": (
            "2022-11-28"
        )
    }

    logger.info(
        f"Downloading repository snapshot "
        f"for {repo_id}"
    )

    response = requests.get(
        zip_url,
        headers=headers,
        stream=True
    )

    response.raise_for_status()

    zip_bytes = io.BytesIO(
        response.content
    )

    extract_path = os.path.join(
        TEMP_REPO_DIR,
        repo_name
    )

    # Remove old extracted repo
    if os.path.exists(extract_path):

        shutil.rmtree(extract_path)

        logger.info(
            f"Removed old temp repo: "
            f"{extract_path}"
        )

    # Extract ZIP archive
    with zipfile.ZipFile(
        zip_bytes,
        "r"
    ) as zip_ref:

        zip_ref.extractall(
            extract_path
        )

    extracted_folders = os.listdir(
        extract_path
    )

    if not extracted_folders:

        logger.error(
            f"Repository extraction failed "
            f"for {repo_id}"
        )

        raise Exception(
            "Repository extraction failed"
        )

    final_repo_path = os.path.join(
        extract_path,
        extracted_folders[0]
    )

    logger.info(
        f"Repository extracted successfully: "
        f"{final_repo_path}"
    )

    return final_repo_path


def cleanup_repository(
    repo_path
):

    """
    Deletes temporary repository snapshot.
    """

    try:

        root_dir = os.path.dirname(
            os.path.dirname(repo_path)
        )

        if os.path.exists(root_dir):

            shutil.rmtree(root_dir)

            logger.info(
                f"Cleaned temporary repo: "
                f"{root_dir}"
            )

    except Exception as e:

        logger.error(
            f"Cleanup failed: {e}"
        )