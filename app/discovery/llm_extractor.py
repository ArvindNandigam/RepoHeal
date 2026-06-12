from __future__ import annotations

import json
import logging
from groq import Groq, BadRequestError, APIStatusError

from app.config import get_settings

from app.discovery.regex_extractor import extract_relationships_regex

logger = logging.getLogger(__name__)

# llama-3.3-70b-versatile has 128K token context window.
# Rough estimate: 1 token ~= 4 chars. Reserve ~20K tokens for completion.
# Budget for the prompt (system + user): ~108K tokens ~= 432K chars.
# System prompt is fixed, header is small — the rest goes to snippets.
_SYS_PROMPT_CHARS = 683
_HEADER_OVERHEAD = 200  # approximate chars for "Target symbol: ... Library: ... Ranked Sources: ..."
_SEPARATOR = "\n\n---\n\n"
_MAX_BATCH_CHARS = 400_000  # generous per-batch limit (~100K tokens)

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

IMPORTANT: Use the FULL dotted path for both "from" and "to" fields (e.g. "pandas.DataFrame.append", not just "append").
Valid relations: "deprecated_in_favor_of", "deprecated_in", "removed_in", "replaced_by", "renamed_to", "moved_to", "superseded_by".
Use "deprecated_in_favor_of" when the old symbol is deprecated and a replacement is explicitly mentioned. Use "deprecated_in" when a deprecation version is stated. Use "removed_in" when removal is explicitly stated.
"""


def _batch_snippets(snippets: list[str], symbol: str, library: str, source_context: list[dict]) -> list[list[str]]:
    """
    Split snippets into batches that each fit within the per-budget char limit.
    Preserves all snippets — no truncation, no `[:10]` cap.
    """
    context_str = json.dumps(
        [{"title": c.get("title"), "url": c.get("url")} for c in source_context], indent=2
    ) if source_context else "[]"
    header = f"Target symbol: {symbol}\nLibrary: {library}\n\nRanked Sources:\n{context_str}\n\nSnippets:\n"
    overhead = _SYS_PROMPT_CHARS + len(header)

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_size = 0

    for s in snippets:
        snippet_cost = len(s) + len(_SEPARATOR)
        batch_overhead = overhead + len(_SEPARATOR) * max(0, len(current_batch) - 1)
        if current_batch and (current_size + snippet_cost + batch_overhead > _MAX_BATCH_CHARS):
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append(s)
        current_size += snippet_cost

    if current_batch:
        batches.append(current_batch)

    return batches


def _send_groq_batch(
    client: Groq,
    model: str,
    symbol: str,
    library: str,
    batch_snippets: list[str],
    source_context: list[dict],
) -> list[dict]:
    """Send a single batch of snippets to Groq and return parsed relationships."""
    context_str = json.dumps(
        [{"title": c.get("title"), "url": c.get("url")} for c in source_context], indent=2
    ) if source_context else "[]"
    combined = _SEPARATOR.join(batch_snippets)
    user_prompt = (
        f"Target symbol: {symbol}\nLibrary: {library}\n\n"
        f"Ranked Sources:\n{context_str}\n\nSnippets:\n{combined}"
    )

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    logger.debug(
        "Groq batch: library=%s symbol=%s model=%s sys=%d user=%d chars",
        library, symbol, model, _SYS_PROMPT_CHARS, len(user_prompt),
    )

    for attempt in range(3):
        try:
            completion = client.chat.completions.create(**request_body)
            response_text = completion.choices[0].message.content
            if not response_text:
                logger.warning("Groq returned empty response (attempt %d)", attempt + 1)
                continue

            parsed = json.loads(response_text)
            rels = parsed.get("relationships", [])
            for r in rels:
                r["extraction_method"] = "groq"
            return rels

        except BadRequestError as e:
            error_detail = e.body if isinstance(e.body, dict) else {"raw": str(e.body)}
            logger.error(
                "Groq HTTP 400 (attempt %d/3): %s | library=%s symbol=%s | sys=%d user=%d chars | body=%s",
                attempt + 1, e.message, library, symbol,
                _SYS_PROMPT_CHARS, len(user_prompt),
                json.dumps(error_detail),
            )
            if attempt == 2:
                return []

        except APIStatusError as e:
            logger.error(
                "Groq HTTP %d (attempt %d/3): %s | library=%s symbol=%s",
                e.status_code, attempt + 1, e.message, library, symbol,
            )
            if attempt == 2:
                return []

        except Exception as e:
            logger.error(
                "Groq extraction failed (attempt %d/3): %s | library=%s symbol=%s",
                attempt + 1, e, library, symbol,
            )
            if attempt == 2:
                return []

    return []


def extract_relationships_groq(symbol: str, library: str, snippets: list[str], source_context: list[dict]) -> list[dict]:
    settings = get_settings()
    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("GROQ_API_KEY not set. Cannot run LLM extraction.")
        return []

    client = Groq(api_key=api_key)
    model = settings.groq_model

    # Batch snippets to preserve ALL information — no `[:10]` cap, no truncation
    batches = _batch_snippets(snippets, symbol, library, source_context)
    logger.debug("Groq: %d snippet(s) split into %d batch(es)", len(snippets), len(batches))

    all_rels: list[dict] = []
    for i, batch in enumerate(batches):
        batch_rels = _send_groq_batch(client, model, symbol, library, batch, source_context)
        all_rels.extend(batch_rels)

    return all_rels
