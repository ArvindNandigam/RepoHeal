import io
import zipfile
from datetime import datetime, timezone

import gridfs
from bson import ObjectId

from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

ZIP_BUCKET = "repo_zips"
EXTRACTED_BUCKET = "repo_files"
REPO_FILE_INDEX = "repo_file_index"


def _get_fs(bucket: str) -> gridfs.GridFS:
    return gridfs.GridFS(get_mongo_db(), bucket)


def store_zip_stream(
    repo_owner: str, repo_name: str, response_iter, content_length: int | None = None
) -> ObjectId:
    """Stream ZIP download chunks directly into GridFS (O(1) memory, O(0) local disk)."""
    fs = _get_fs(ZIP_BUCKET)
    metadata = {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "stored_at": datetime.now(timezone.utc),
        "content_length": content_length,
    }
    filename = f"{repo_owner}/{repo_name}.zip"
    total = 0
    buf = io.BytesIO()
    for chunk in response_iter:
        if chunk:
            total += len(chunk)
            buf.write(chunk)
    buf.seek(0)
    written = fs.put(buf, filename=filename, metadata=metadata)
    logger.info(
        f"Stored {repo_owner}/{repo_name}.zip in GridFS ({total / 1024 / 1024:.1f}MB), id={written}"
    )
    return written


def extract_files_to_memory(
    zip_id: ObjectId, repo_owner: str, repo_name: str
) -> dict[str, bytes]:
    """Read ZIP from GridFS, extract all files to a memory dict.
    Returns {relative_path: content_bytes}.
    """
    fs = _get_fs(ZIP_BUCKET)
    grid_file = fs.get(zip_id)
    raw = grid_file.read()
    buf = io.BytesIO(raw)
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(buf, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            result[info.filename] = zf.read(info.filename)
    logger.info(
        f"Extracted {len(result)} files from GridFS ZIP {zip_id} for {repo_owner}/{repo_name}"
    )
    return result


def cleanup_zip(zip_id: ObjectId) -> None:
    """Delete a ZIP file from GridFS."""
    try:
        fs = _get_fs(ZIP_BUCKET)
        fs.delete(zip_id)
        logger.info(f"Deleted GridFS ZIP {zip_id}")
    except Exception as e:
        logger.warning(f"Failed to delete GridFS ZIP {zip_id}: {e}")


def cleanup_repo_files(repo_owner: str, repo_name: str) -> int:
    """Delete all GridFS files associated with a repo (both ZIP and extracted)."""
    count = 0
    for bucket in (ZIP_BUCKET, EXTRACTED_BUCKET):
        fs = _get_fs(bucket)
        for gf in fs.find({"repo_owner": repo_owner, "repo_name": repo_name}):
            try:
                fs.delete(gf._id)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to delete GridFS file {gf._id}: {e}")
    if count:
        logger.info(f"Cleaned up {count} GridFS files for {repo_owner}/{repo_name}")
    return count
