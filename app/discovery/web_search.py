from __future__ import annotations

import logging
from duckduckgo_search import DDGS

from app.config import get_settings

logger = logging.getLogger(__name__)

REJECTED_DOMAINS = {
    "medium.com", "towardsdatascience.com", "dev.to",
    "stackoverflow.com", "geeksforgeeks.org", "w3schools.com",
    "tutorialspoint.com", "javatpoint.com", "programiz.com",
    "freecodecamp.org",
}

def generate_search_queries(symbol: str) -> list[str]:
    return [
        f"{symbol} replaced by",
        f"{symbol} deprecated use instead",
        f"{symbol} migration guide",
        f"{symbol} renamed to",
        f"{symbol} removed how to fix",
        f"{symbol} breaking changes",
    ]

def filter_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    
    for result in results:
        url = str(result.get("href") or "").lower()
        if not url or url in seen_urls:
            continue
            
        # Reject domains known to be low quality / SEO blogs
        if any(domain in url for domain in REJECTED_DOMAINS):
            continue
            
        seen_urls.add(url)
        filtered.append(result)
        
    return filtered

def search(queries: list[str]) -> list[dict[str, str]]:
    settings = get_settings()
    max_results = settings.max_search_results
    all_results: list[dict[str, str]] = []
    
    with DDGS() as ddgs:
        for query in queries:
            try:
                # Ask duckduckgo
                results = list(ddgs.text(query, max_results=max_results))
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Search query '{query}' failed: {e}")
                
    # Deduplicate and filter
    filtered = filter_results(all_results)
    
    # Sort to prioritize github issues/discussions and official docs
    def sort_key(item: dict[str, str]) -> int:
        url = str(item.get("href") or "").lower()
        if "github.com" in url and ("/issues/" in url or "/discussions/" in url or "/pull/" in url):
            return 0
        if "docs." in url or "readthedocs" in url:
            return 1
        if "github.com" in url:
            return 2
        return 3
        
    return sorted(filtered, key=sort_key)
