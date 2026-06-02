from __future__ import annotations

import json
import logging
import os
from groq import Groq

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a migration extraction AI. 
Extract facts only. Do not infer. Do not recommend. Do not hallucinate. Return JSON only.
You must find relationships where the old symbol has been removed, deprecated, or replaced by a new symbol.
If there is no clear replacement or migration, return an empty relationships list.

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

Valid relations: "replaced_by", "renamed_to", "use_instead", "superseded_by".
"""

def extract_relationships(symbol: str, snippets: list[str]) -> list[dict]:
    if not snippets:
        return []
        
    settings = get_settings()
    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("GROQ_API_KEY not set. Cannot run LLM extraction.")
        return []

    client = Groq(api_key=api_key)
    
    # Combine snippets safely
    combined_snippets = "\n\n---\n\n".join(snippets[:10]) # Limit to 10 snippets to fit in context window comfortably
    
    user_prompt = f"Target symbol: {symbol}\n\nSnippets:\n{combined_snippets}"
    
    try:
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
        return parsed.get("relationships", [])
    except Exception as e:
        logger.error(f"Groq extraction failed: {e}")
        return []
