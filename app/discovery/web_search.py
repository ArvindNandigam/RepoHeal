from __future__ import annotations

import logging
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

def generate_search_queries(symbol: str, library: str) -> list[str]:
    symbol_tail = symbol.split(".")[-1]
    return [
        # Symbol-focused
        f"{symbol} replacement",
        f"{symbol} migration",
        f"{symbol} deprecated",
        f"{symbol} removed",
        f"{symbol} use instead",
        f"{symbol} breaking changes",
        f"{symbol} upgrade guide",
        # Library-aware
        f"{library} {symbol_tail} migration guide",
        f"{library} {symbol_tail} release notes",
        f"{library} {symbol_tail} replacement symbol",
    ]

def serper_search(queries: list[str]) -> list[dict[str, str]]:
    settings = get_settings()
    api_key = settings.serper_api_key
    if not api_key:
        logger.warning("SERPER_API_KEY not set. Cannot run web search.")
        return []

    max_results = settings.max_search_results
    all_results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    with httpx.Client(timeout=10.0) as client:
        for query in queries:
            if len(all_results) >= max_results:
                break
                
            payload = {
                "q": query,
                "num": 10
            }
            try:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                organic = data.get("organic", [])
                for result in organic:
                    if len(all_results) >= max_results:
                        break
                    
                    link = result.get("link")
                    if not link or link in seen_urls:
                        continue
                        
                    seen_urls.add(link)
                    all_results.append({
                        "title": result.get("title", ""),
                        "url": link,
                        "snippet": result.get("snippet", ""),
                        "position": result.get("position", 0),
                    })
            except Exception as e:
                logger.error(f"Serper search query '{query}' failed: {e}")
                
    return all_results

def rank_sources(results: list[dict[str, str]]) -> list[dict[str, str]]:
    ranked = []
    for result in results:
        url = result.get("url", "").lower()
        score = 10
        
        if "docs." in url or "readthedocs" in url:
            score = 100
        elif any(keyword in url for keyword in ["migration", "upgrade", "release", "changelog"]):
            score = 90
        elif "github.com" in url:
            score = 80
        elif "pypi.org" in url:
            score = 60
        elif "stackoverflow.com" in url:
            score = 30
        elif any(domain in url for domain in ["medium.com", "dev.to", "towardsdatascience.com"]):
            score = 20
            
        ranked.append({**result, "score": score})
        
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:5]
