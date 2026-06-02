from __future__ import annotations

import logging
import httpx
from html.parser import HTMLParser
import re

from app.validators.sources import is_approved_source_url

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
        logger.warning(f"Failed to fetch page {url}: {e}")
        return None

def extract_relevant_sections(text: str, symbol: str) -> list[str]:
    # Very basic window extraction around the symbol
    snippets: list[str] = []
    window = 300
    
    lowered = text.lower()
    symbol_lower = symbol.lower()
    start = 0
    while True:
        idx = lowered.find(symbol_lower, start)
        if idx == -1:
            break
        
        snip_start = max(0, idx - window)
        snip_end = min(len(text), idx + len(symbol) + window)
        snippet = text[snip_start:snip_end].strip()
        
        # Avoid near-duplicates
        if not any(snippet in s or s in snippet for s in snippets):
            snippets.append(snippet)
            
        start = idx + len(symbol)
        
    return snippets
