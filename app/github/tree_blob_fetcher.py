import base64
import time

import requests

from app.github.auth import get_installation_token
from app.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_FILE_NAMES = frozenset({
    "requirements.txt", "setup.py", "setup.cfg",
    "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock",
})

RATE_LIMIT_URL = "https://api.github.com/rate_limit"
REQUEST_DELAY_S = 0.1
RATE_CHECK_INTERVAL = 100
RATE_SAFETY_BUFFER = 150
PROGRESS_INTERVAL = 50


def _check_rate_limit(session, token: str) -> dict:
    resp = session.get(RATE_LIMIT_URL, timeout=10)
    resp.raise_for_status()
    return resp.json().get("resources", {}).get("core", {})


def _fetch_tree_blobs(
    token: str, owner: str, repo: str, commit_sha: str,
    progress_callback=None, owner_repo_name: str = "",
) -> dict[str, str]:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    session = requests.Session()
    session.headers.update(headers)

    try:
        commit_url = f"https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}"
        commit_resp = session.get(commit_url, timeout=15)
        commit_resp.raise_for_status()
        tree_sha = commit_resp.json()["tree"]["sha"]

        tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1"
        tree_resp = session.get(tree_url, timeout=30)
        tree_resp.raise_for_status()
        entries = tree_resp.json().get("tree", [])
        logger.info(f"Tree API returned {len(entries)} total entries for {owner}/{repo}")

        wanted = []
        for entry in entries:
            if entry.get("type") != "blob":
                continue
            path: str = entry["path"]
            if path.endswith(".py") or path.endswith(".ipynb"):
                wanted.append(entry)
            else:
                name = path.rsplit("/", 1)[-1] if "/" in path else path
                if name in CONFIG_FILE_NAMES:
                    wanted.append(entry)

        total = len(wanted)
        py_count = sum(1 for e in wanted if e["path"].endswith(".py"))
        nb_count = sum(1 for e in wanted if e["path"].endswith(".ipynb"))
        cfg_count = total - py_count - nb_count
        logger.info(f"Tree+Blob: {py_count} .py, {nb_count} .ipynb, {cfg_count} config files")

        if progress_callback:
            progress_callback(
                owner_repo_name, "analyzing", 12,
                f"Fetching {total} files via GitHub Blob API (0%)", "blob_api"
            )

        result: dict[str, str] = {}
        rate_remaining = None
        rate_reset_at = 0
        _blob_start = time.time()

        def _eta_msg(done: int, out_of: int, extra: str = "") -> str:
            if done == 0:
                eta = "calculating..."
            else:
                elapsed = time.time() - _blob_start
                rate = done / elapsed if elapsed > 0 else 0
                remaining = out_of - done
                eta_s = remaining / rate if rate > 0 else 0
                if eta_s < 120:
                    eta = f"~{eta_s:.0f}s"
                elif eta_s < 3600:
                    eta = f"~{eta_s/60:.0f}m {eta_s%60:.0f}s"
                else:
                    eta = f"~{eta_s/3600:.1f}h"
            base = f"Fetching {done}/{out_of} files ({int(done/out_of*100)}%)"
            return f"{base}, {eta} remaining" + (f" — {extra}" if extra else "")

        for i, entry in enumerate(wanted):
            path = entry["path"]
            sha = entry["sha"]

            if i > 0 and i % RATE_CHECK_INTERVAL == 0:
                try:
                    rl = _check_rate_limit(session, token)
                    rate_remaining = rl.get("remaining", 0)
                    rate_reset_at = rl.get("reset", 0)
                    if rate_remaining < RATE_SAFETY_BUFFER and rate_reset_at:
                        wait = max(rate_reset_at - time.time() + 5, 0)
                        msg = f"Approaching rate limit ({rate_remaining} remaining), pausing {wait:.0f}s"
                        logger.warning(msg)
                        if progress_callback:
                            pct = int((i / total) * 40) + 12 if total else 12
                            progress_callback(owner_repo_name, "analyzing", min(pct, 50), msg, "blob_api")
                        if wait > 0:
                            time.sleep(wait)
                except Exception:
                    pass

            blob_url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{sha}"
            for attempt in range(3):
                blob_resp = session.get(blob_url, timeout=15)
                if blob_resp.status_code == 429:
                    retry_after = int(blob_resp.headers.get("retry-after", 60))
                    logger.warning(f"Rate limited, waiting {retry_after}s (retry {attempt+1}/3)")
                    if progress_callback:
                        progress_callback(
                            owner_repo_name, "analyzing", min(int((i / total) * 40) + 12, 50),
                            _eta_msg(i + 1, total, f"rate limited, pausing {retry_after}s"),
                            "blob_api"
                        )
                    time.sleep(retry_after + 1)
                    continue
                elif blob_resp.status_code == 403:
                    text_lower = blob_resp.text.lower()
                    if "rate limit" in text_lower or "rate_limit" in text_lower:
                        retry_after = int(blob_resp.headers.get("retry-after", 60))
                        logger.warning(f"Rate limited (403), waiting {retry_after}s (retry {attempt+1}/3)")
                        if progress_callback:
                            progress_callback(
                                owner_repo_name, "analyzing", min(int((i / total) * 40) + 12, 50),
                                _eta_msg(i + 1, total, f"rate limited, pausing {retry_after}s"),
                                "blob_api"
                            )
                        time.sleep(retry_after + 1)
                        continue
                blob_resp.raise_for_status()
                break
            else:
                raise RuntimeError(
                    f"Failed to fetch blob {sha} after 3 retries (rate limited)"
                )

            blob_data = blob_resp.json()
            raw = base64.b64decode(blob_data["content"])
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            result[path] = text

            if total > 0 and progress_callback and (i + 1) % PROGRESS_INTERVAL == 0:
                progress_callback(
                    owner_repo_name, "analyzing", min(int(((i + 1) / total) * 40) + 12, 50),
                    _eta_msg(i + 1, total), "blob_api"
                )

            time.sleep(REQUEST_DELAY_S)

        if progress_callback:
            progress_callback(
                owner_repo_name, "analyzing", 52,
                f"Fetched {len(result)} files, starting analysis", "blob_api"
            )

        logger.info(f"Tree+Blob fetcher completed: {len(result)} files")
        return result

    finally:
        session.close()


def fetch_repository_contents(
    installation_id: int,
    owner: str,
    repo: str,
    commit_sha: str,
    owner_repo_name: str,
    progress_callback=None,
) -> dict[str, str]:
    if progress_callback:
        progress_callback(
            owner_repo_name, "analyzing", 10,
            "Fetching file tree via GitHub API", "tree_api"
        )

    token = get_installation_token(installation_id)
    result = _fetch_tree_blobs(
        token, owner, repo, commit_sha,
        progress_callback=progress_callback, owner_repo_name=owner_repo_name,
    )

    if progress_callback:
        progress_callback(
            owner_repo_name, "analyzing", 55,
            f"Repository contents fetched ({len(result)} files), analyzing", "tree_api"
        )

    return result
