from __future__ import annotations

import logging
import httpx
from html.parser import HTMLParser
import re
from urllib.parse import urljoin
from app.validators.sources import is_approved_source_url
from app.config import get_settings

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

def fetch_page(url: str, timeout: float | None = None) -> str | None:
    if not is_approved_source_url(url):
        logger.warning("Rejected fetch for unapproved source URL: %s", url)
        return None
    settings = get_settings()
    timeout = timeout if timeout is not None else settings.upstream_timeout_seconds
    current_url = url
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, verify=True) as client:
            for redirect_count in range(settings.max_redirects + 1):
                response = client.get(current_url)
                status_code = response.status_code if isinstance(response.status_code, int) else 200
                if 300 <= status_code < 400:
                    location = response.headers.get("location")
                    if not location or redirect_count >= settings.max_redirects:
                        return None
                    current_url = urljoin(current_url, location)
                    if not is_approved_source_url(current_url):
                        logger.warning("Rejected redirect to unapproved source URL: %s", current_url)
                        return None
                    continue

                response.raise_for_status()
                content_type_header = response.headers.get("content-type", "")
                content_type = content_type_header.split(";", 1)[0].strip().lower() if isinstance(content_type_header, str) else ""
                if content_type and content_type not in settings.allowed_content_types:
                    logger.warning("Rejected unsupported content type %s for %s", content_type, current_url)
                    return None
                content_length = response.headers.get("content-length")
                if isinstance(content_length, str) and content_length and int(content_length) > settings.max_upstream_response_bytes:
                    logger.warning("Rejected oversized response for %s", current_url)
                    return None
                content = response.content
                if not isinstance(content, bytes):
                    content = response.text.encode("utf-8")
                if len(content) > settings.max_upstream_response_bytes:
                    logger.warning("Rejected oversized response for %s", current_url)
                    return None
                encoding = response.encoding if isinstance(response.encoding, str) else "utf-8"
                return _extract_text(content.decode(encoding or "utf-8", errors="replace"))
            return None
    except (ValueError, UnicodeError) as e:
        logger.debug("Failed to validate page %s: %s", url, e)
        return None
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
