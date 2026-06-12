from __future__ import annotations

import json
import logging
from groq import Groq, BadRequestError, APIStatusError

from app.config import get_settings

logger = logging.getLogger(__name__)

_SEPARATOR = "\n\n---\n\n"
_MAX_BATCH_CHARS = 100_000
_FALLBACK_MODEL = "llama-3.1-8b-instant"

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


def _build_user_prompt(symbol: str, library: str, batch: list[str], source_context: list[dict]) -> str:
    context_str = json.dumps(
        [{"title": c.get("title"), "url": c.get("url")} for c in source_context], indent=2
    ) if source_context else "[]"
    combined = _SEPARATOR.join(batch)
    return (
        f"Target symbol: {symbol}\nLibrary: {library}\n\n"
        f"Ranked Sources:\n{context_str}\n\nSnippets:\n{combined}"
    )


def _batch_snippets(snippets: list[str], symbol: str, library: str, source_context: list[dict]) -> list[list[str]]:
    header = _build_user_prompt(symbol, library, [], source_context)
    overhead = len(SYSTEM_PROMPT) + len(header)

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_size = 0

    for s in snippets:
        cost = len(s) + len(_SEPARATOR)
        batch_header = overhead + len(_SEPARATOR) * max(0, len(current_batch))
        if current_batch and (current_size + cost + batch_header > _MAX_BATCH_CHARS):
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append(s)
        current_size += cost

    if current_batch:
        batches.append(current_batch)

    return batches


def _parse_json_response(text: str | None) -> list[dict]:
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    rels = parsed.get("relationships", []) if isinstance(parsed, dict) else []
    for r in rels:
        r["extraction_method"] = "groq"
    return rels


def _call_groq(
    client: Groq,
    model: str,
    messages: list[dict],
    use_json_format: bool,
    symbol: str,
    library: str,
) -> list[dict]:
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_completion_tokens": 4096,
    }
    if use_json_format:
        kwargs["response_format"] = {"type": "json_object"}

    logger.debug(
        "Groq call: library=%s symbol=%s model=%s json_format=%s messages_chars=%d",
        library, symbol, model, use_json_format, sum(len(m.get("content", "")) for m in messages),
    )

    completion = client.chat.completions.create(**kwargs)
    return _parse_json_response(completion.choices[0].message.content)


def _try_extraction(
    client: Groq,
    model: str,
    symbol: str,
    library: str,
    user_prompt: str,
) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    # Strategy 1: with json_object response_format
    try:
        return _call_groq(client, model, messages, use_json_format=True, symbol=symbol, library=library)
    except BadRequestError as e:
        body = e.body if isinstance(e.body, dict) else {"raw": str(e.body)}
        logger.warning(
            "Groq 400 with json_object (library=%s symbol=%s model=%s): %s",
            library, symbol, model, json.dumps(body),
        )
    except APIStatusError as e:
        logger.warning(
            "Groq HTTP %d (library=%s symbol=%s model=%s): %s",
            e.status_code, library, symbol, model, e.message,
        )
        return []

    # Strategy 2: without response_format (parse JSON from raw text)
    try:
        return _call_groq(client, model, messages, use_json_format=False, symbol=symbol, library=library)
    except APIStatusError as e:
        logger.warning(
            "Groq HTTP %d without json_object (library=%s symbol=%s model=%s): %s",
            e.status_code, library, symbol, model, e.message,
        )
        return []


def extract_relationships_groq(symbol: str, library: str, snippets: list[str], source_context: list[dict]) -> list[dict]:
    settings = get_settings()
    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("GROQ_API_KEY not set. Cannot run LLM extraction.")
        return []

    client = Groq(api_key=api_key)
    primary_model = settings.groq_model

    batches = _batch_snippets(snippets, symbol, library, source_context)
    logger.info("Groq: %d snippet(s) split into %d batch(es)", len(snippets), len(batches))

    all_rels: list[dict] = []

    for i, batch in enumerate(batches):
        user_prompt = _build_user_prompt(symbol, library, batch, source_context)

        # Try primary model first
        rels = _try_extraction(client, primary_model, symbol, library, user_prompt)

        # Fallback to secondary model if primary returned nothing
        if not rels and primary_model != _FALLBACK_MODEL:
            logger.info("Groq primary model %s returned nothing, trying fallback %s", primary_model, _FALLBACK_MODEL)
            rels = _try_extraction(client, _FALLBACK_MODEL, symbol, library, user_prompt)

        if rels:
            logger.info("Groq batch %d/%d: extracted %d relationship(s)", i + 1, len(batches), len(rels))
            all_rels.extend(rels)

    return all_rels
