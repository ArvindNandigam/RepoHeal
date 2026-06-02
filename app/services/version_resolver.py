from __future__ import annotations

import httpx
import logging

logger = logging.getLogger(__name__)

def resolve_latest_version(library: str) -> str | None:
    pypi_url = f"https://pypi.org/pypi/{library}/json"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(pypi_url)
            response.raise_for_status()
            pypi_json = response.json()
            return pypi_json.get("info", {}).get("version")
    except Exception as e:
        logger.warning(f"Failed to resolve latest version for {library} from PyPI: {e}")
        return None

def resolve_library_metadata(library: str) -> dict:
    pypi_url = f"https://pypi.org/pypi/{library}/json"
    metadata = {
        "library": library,
        "latest_version": None,
        "official_docs": None,
        "github_repo": None,
        "pypi_url": pypi_url
    }
    
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(pypi_url)
            response.raise_for_status()
            pypi_json = response.json()
            
            info = pypi_json.get("info", {})
            metadata["latest_version"] = info.get("version")
            
            project_urls = info.get("project_urls") or {}
            
            # Find Github
            for k, v in project_urls.items():
                k_lower = k.lower()
                if "source" in k_lower or "github" in k_lower or "repo" in k_lower:
                    metadata["github_repo"] = v
                    break
            if not metadata["github_repo"]:
                home_page = info.get("home_page")
                if home_page and "github.com" in home_page:
                    metadata["github_repo"] = home_page
                    
            # Find Docs
            for k, v in project_urls.items():
                k_lower = k.lower()
                if "doc" in k_lower:
                    metadata["official_docs"] = v
                    break
            
            return metadata
            
    except Exception as e:
        logger.warning(f"Failed to resolve library metadata for {library} from PyPI: {e}")
        return metadata
