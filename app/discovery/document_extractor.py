from __future__ import annotations

import logging
import httpx
from html.parser import HTMLParser
import re

logger = logging.getLogger(__name__)

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()

def _extract_text(content: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(content)
    text = extractor.text()
    return text or re.sub(r"\s+", " ", content).strip()

def fetch_page(url: str, timeout: float = 10.0) -> str | None:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, verify=False) as client:
            response = client.get(url)
            response.raise_for_status()
            return _extract_text(response.text)
    except Exception as e:
        logger.debug("Failed to fetch page %s: %s", url, e)
        return None

def extract_relevant_sections(text: str, symbol: str) -> list[str]:
    """
    Window extraction around the symbol in fetched page text.
    Uses cascading search: full symbol → class.method → method tail.
    """
    parts = symbol.split(".")
    
    # Build search terms from most specific to least specific
    search_terms: list[str] = []
    search_terms.append(symbol)                          # full: pydantic.BaseModel.parse_obj
    if len(parts) >= 2:
        search_terms.append(".".join(parts[-2:]))        # class.method: BaseModel.parse_obj
    if len(parts) >= 1:
        search_terms.append(parts[-1])                   # tail: parse_obj
    
    window = 50
    
    for term in search_terms:
        snippets = _extract_windows(text, term, window)
        if snippets:
            return snippets
    
    return []


def _extract_windows(text: str, term: str, window: int) -> list[str]:
    """Extract text windows around occurrences of term in text."""
    snippets: list[str] = []
    lowered = text.lower()
    term_lower = term.lower()
    start = 0
    
    while True:
        idx = lowered.find(term_lower, start)
        if idx == -1:
            break
        
        snip_start = max(0, idx - window)
        snip_end = min(len(text), idx + len(term) + window)
        snippet = text[snip_start:snip_end].strip()
        
        # Avoid near-duplicates
        if not any(snippet in s or s in snippet for s in snippets):
            snippets.append(snippet)
            
        start = idx + len(term)
        
    return snippets
