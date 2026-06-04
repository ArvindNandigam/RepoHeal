from __future__ import annotations

import json
import logging
from groq import Groq

from app.config import get_settings

from app.discovery.regex_extractor import extract_relationships_regex

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an evidence extraction engine.
Your task is to identify migration relationships.
Use ONLY the provided evidence.
Do NOT infer.
Do NOT guess.
Do NOT hallucinate.
Do NOT use prior knowledge.
Return JSON only.
If there is no clear replacement or migration in the evidence, return an empty relationships list.

JSON format:
{
  "relationships": [
    {
      "from": "old_symbol",
      "relation": "replaced_by",
      "to": "new_symbol",
      "confidence": 1.0
    }
  ]
}

Valid relations: "replaced_by", "renamed_to", "moved_to", "deprecated_in", "removed_in", "superseded_by".
"""

def _groq_extract(symbol: str, library: str, snippets: list[str], source_context: list[dict]) -> list[dict]:
    settings = get_settings()
    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("GROQ_API_KEY not set. Cannot run LLM extraction.")
        return []

    try:
        client = Groq(api_key=api_key)
        
        # Combine snippets safely
        combined_snippets = "\n\n---\n\n".join(snippets[:10])
        
        context_str = json.dumps([{"title": c.get("title"), "url": c.get("url")} for c in source_context], indent=2)
        user_prompt = f"Target symbol: {symbol}\nLibrary: {library}\n\nRanked Sources:\n{context_str}\n\nSnippets:\n{combined_snippets}"
        
        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        response_text = completion.choices[0].message.content
        if not response_text:
            return []
            
        parsed = json.loads(response_text)
        rels = parsed.get("relationships", [])
        for r in rels:
            r["extraction_method"] = "groq"
        return rels
    except Exception as e:
        logger.error(f"Groq extraction failed: {e}")
        return []

def extract_relationships(symbol: str, library: str, snippets: list[str], source_context: list[dict]) -> list[dict]:
    if not snippets:
        return []
        
    # 1. Try regex first
    regex_rels = extract_relationships_regex(symbol, library, snippets)
    if regex_rels:
        return regex_rels
        
    # 2. Fallback to Groq
    return _groq_extract(symbol, library, snippets, source_context)
