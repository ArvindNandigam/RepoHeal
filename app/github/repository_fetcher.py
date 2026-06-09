import os
import shutil
import tempfile
import zipfile

import requests

from app.github.auth import get_installation_token
from app.github.installations import get_repository_installation
from app.utils.logger import get_logger

logger = get_logger(__name__)

TEMP_REPO_DIR = "/tmp/repoheal"


def ensure_temp_directory():
    os.makedirs(TEMP_REPO_DIR, exist_ok=True)


def get_repository_archive_url(repo_owner, repo_name, ref=None):
    ref_suffix = f"/{ref}" if ref else ""
    return f"https://api.github.com/repos/{repo_owner}/{repo_name}/zipball{ref_suffix}"


def download_repository_snapshot(repo_owner, repo_name, ref=None):
    """
    Downloads repository ZIP snapshot to disk (O(1) memory for download).
    Uses streaming writes to a temp file, then extracts from disk.
    The temp ZIP file is deleted after extraction.
    """
    ensure_temp_directory()
    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(f"Preparing repository download: {repo_id}")

    installation = get_repository_installation(repo_owner, repo_name)
    if not installation:
        logger.warning(f"RepoHeal not installed on {repo_id}")
        raise PermissionError("RepoHeal is not installed on this repository")

    installation_id = installation["id"]
    logger.info(f"Using installation ID: {installation_id}")

    access_token = get_installation_token(installation_id)
    zip_url = get_repository_archive_url(repo_owner, repo_name, ref=ref)

    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    logger.info(f"Downloading repository snapshot for {repo_id}")

    # Phase 7: Check content-length header before downloading (if available)
    response = requests.get(zip_url, headers=headers, stream=True)
    response.raise_for_status()

    from app.config import settings as _cfg
    content_length = response.headers.get("content-length")
    if content_length:
        zip_size_mb = int(content_length) / 1024 / 1024
        max_zip = _cfg.MAX_ZIP_SIZE_MB
        if zip_size_mb > max_zip:
            response.close()
            raise ValueError(
                f"Repository ZIP is {zip_size_mb:.0f}MB which exceeds the maximum allowed size of {max_zip}MB. "
                f"Skipping analysis to prevent OOM."
            )
        logger.info(f"ZIP size: {zip_size_mb:.1f}MB (limit: {max_zip}MB)")

    # Stream ZIP to temp file on disk — O(1) memory
    zip_tmp = tempfile.NamedTemporaryFile(
        dir=TEMP_REPO_DIR, suffix=".zip", delete=False
    )
    zip_path = zip_tmp.name
    try:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                zip_tmp.write(chunk)
        zip_tmp.close()
        logger.info(f"ZIP saved to disk: {zip_path} ({os.path.getsize(zip_path) / 1024 / 1024:.1f}MB)")

        extract_path = os.path.join(TEMP_REPO_DIR, repo_name)
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)

        # Open ZipFile from disk path — not from memory
        extracted_size = 0
        py_count = 0
        total_count = 0

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # Phase 7: Estimate extraction size and file counts before extracting
            for info in zip_ref.infolist():
                total_count += 1
                extracted_size += info.file_size
                if info.filename.endswith(".py"):
                    py_count += 1

            from app.config import settings as _cfg2
            max_extracted_mb = _cfg2.MAX_EXTRACTED_SIZE_MB
            max_files = _cfg2.MAX_FILE_COUNT
            max_py_files = _cfg2.MAX_PYTHON_FILE_COUNT

            extracted_mb = extracted_size / 1024 / 1024
            if extracted_mb > max_extracted_mb:
                raise ValueError(
                    f"Repository would extract to {extracted_mb:.0f}MB which exceeds the maximum of {max_extracted_mb}MB"
                )
            if total_count > max_files:
                raise ValueError(
                    f"Repository has {total_count} files which exceeds the maximum of {max_files}"
                )
            if py_count > max_py_files:
                raise ValueError(
                    f"Repository has {py_count} Python files which exceeds the maximum of {max_py_files}"
                )

            logger.info(
                f"Extraction plan: {extracted_mb:.1f}MB, {total_count} files ({py_count} .py)"
            )
            zip_ref.extractall(extract_path)

        extracted_folders = os.listdir(extract_path)
        if not extracted_folders:
            logger.error(f"Repository extraction failed for {repo_id}")
            raise Exception("Repository extraction failed")

        final_repo_path = os.path.join(extract_path, extracted_folders[0])
        logger.info(f"Repository extracted successfully: {final_repo_path}")
        return final_repo_path

    finally:
        # Always delete temp ZIP file
        if os.path.exists(zip_path):
            os.unlink(zip_path)
            logger.info(f"Deleted temp ZIP: {zip_path}")


def cleanup_repository(repo_path):
    """Deletes extracted repository directory."""
    try:
        root_dir = os.path.dirname(os.path.dirname(repo_path))
        if os.path.exists(root_dir):
            shutil.rmtree(root_dir)
            logger.info(f"Cleaned temporary repo: {root_dir}")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
