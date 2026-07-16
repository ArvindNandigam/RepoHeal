from __future__ import annotations

import json
import logging
import time
from groq import Groq, BadRequestError, APIStatusError

from app.config import get_settings

logger = logging.getLogger(__name__)

_SEPARATOR = "\n\n---\n\n"
_FALLBACK_MODEL = "llama-3.1-8b-instant"

# Groq FREE tier limits for llama-3.3-70b-versatile:
#   RPM: 30, RPD: 1,000, TPM: 12,000, TPD: 100,000
# 1 token ~= 4 chars. Safe snippet budget: 12,000 chars.
_MAX_BATCH_CHARS = 12_000

_RPM_LIMIT = 30
_RPD_LIMIT = 1_000
_TPM_LIMIT = 12_000
_TPD_LIMIT = 100_000
_SAFE_WAIT_SECONDS = 3.0

_TO_TOKEN_RATIO = 4  # chars per token estimate

_TOKEN_HISTORY: list[tuple[float, int]] = []
_REQUEST_HISTORY: list[float] = []
_LAST_KEY_HASH: int = 0


def _check_key_change() -> None:
    """Clear token history if the API key has changed (key rotation)."""
    global _LAST_KEY_HASH
    settings = get_settings()
    key = settings.groq_api_key or ""
    key_hash = hash(key)
    if _LAST_KEY_HASH != 0 and _LAST_KEY_HASH != key_hash:
        _TOKEN_HISTORY.clear()
        logger.info("Groq API key changed — reset token history")
    _LAST_KEY_HASH = key_hash


def _prune_history() -> None:
    now = time.time()
    cutoff_24h = now - 86400
    _TOKEN_HISTORY[:] = [(ts, t) for ts, t in _TOKEN_HISTORY if ts > cutoff_24h]
    _REQUEST_HISTORY[:] = [ts for ts in _REQUEST_HISTORY if ts > cutoff_24h]


def _check_rpm_budget() -> float:
    """Return seconds to wait to stay under RPM limit."""
    now = time.time()
    cutoff_1m = now - 60
    rpm_used = sum(1 for ts in _REQUEST_HISTORY if ts > cutoff_1m)
    if rpm_used >= _RPM_LIMIT:
        oldest_in_window = min((ts for ts in _REQUEST_HISTORY if ts > cutoff_1m), default=None)
        if oldest_in_window:
            wait = oldest_in_window + 60 - now + 0.5
            return max(wait, 1.0)
    return 0.0


def _check_rpd_budget() -> bool:
    """Return True if we have enough RPD budget."""
    _prune_history()
    rpd_used = len(_REQUEST_HISTORY)
    return rpd_used < _RPD_LIMIT


def _check_tpm_budget(needed: int) -> float:
    """Return seconds to wait to stay under TPM limit."""
    now = time.time()
    cutoff_1m = now - 60
    tpm_used = sum(t for ts, t in _TOKEN_HISTORY if ts > cutoff_1m)
    if tpm_used + needed > _TPM_LIMIT:
        in_window = [(ts, t) for ts, t in _TOKEN_HISTORY if ts > cutoff_1m]
        in_window.sort()
        needed_freed = (tpm_used + needed) - _TPM_LIMIT
        freed = 0
        for ts, t in in_window:
            freed += t
            if freed >= needed_freed:
                wait = ts + 60 - now + 0.5
                return max(wait, 1.0)
    return 0.0


def _check_tpd_budget(needed: int) -> bool:
    """Return True if we have enough TPD budget."""
    _prune_history()
    tpd_used = sum(t for _, t in _TOKEN_HISTORY)
    return tpd_used + needed <= _TPD_LIMIT


def _can_make_request(needed_tokens: int) -> tuple[bool, str | None]:
    """Check all budgets. Returns (can_proceed, skip_reason)."""
    if not _check_rpd_budget():
        return False, "RPD_exhausted"
    if not _check_tpd_budget(needed_tokens):
        return False, "TPD_exhausted"
    return True, None


def _record_request(tokens: int) -> None:
    now = time.time()
    _TOKEN_HISTORY.append((now, tokens))
    _REQUEST_HISTORY.append(now)

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
        "max_tokens": 2048,
    }
    if use_json_format:
        kwargs["response_format"] = {"type": "json_object"}

    total_chars = sum(len(m.get("content", "")) for m in messages)
    estimated_tokens = total_chars // 4
    logger.debug(
        "Groq call: library=%s symbol=%s model=%s json_format=%s ~%d tokens",
        library, symbol, model, use_json_format, estimated_tokens,
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
        body = e.body if isinstance(e.body, dict) else {"raw": str(e.body)}
        logger.warning(
            "Groq HTTP %d (library=%s symbol=%s model=%s): %s",
            e.status_code, library, symbol, model, json.dumps(body),
        )
        return []

    # Strategy 2: without response_format (parse JSON from raw text)
    try:
        return _call_groq(client, model, messages, use_json_format=False, symbol=symbol, library=library)
    except APIStatusError as e:
        logger.info(
            "Groq HTTP %d (library=%s symbol=%s model=%s): %s",
            e.status_code, library, symbol, model, e.body.get("error", {}).get("message", str(e.body)) if isinstance(e.body, dict) else str(e.body),
        )
        return []

    return []


def extract_relationships_groq(symbol: str, library: str, snippets: list[str], source_context: list[dict]) -> tuple[list[dict], bool]:
    """Returns (relationships, budget_exhausted).
    budget_exhausted is True if any batch was skipped due to RPD/TPD exhaustion.
    """
    _check_key_change()
    settings = get_settings()
    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("GROQ_API_KEY not set. Cannot run LLM extraction.")
        return [], False

    client = Groq(api_key=api_key)
    primary_model = settings.groq_model

    batches = _batch_snippets(snippets, symbol, library, source_context)
    logger.info("Groq: %d snippet(s) split into %d batch(es) at %d chars/batch",
                len(snippets), len(batches), _MAX_BATCH_CHARS)

    all_rels: list[dict] = []
    budget_exhausted = False

    for i, batch in enumerate(batches):
        user_prompt = _build_user_prompt(symbol, library, batch, source_context)
        prompt_tokens = len(user_prompt) // 4 + len(SYSTEM_PROMPT) // 4
        total_needed = prompt_tokens + 2048
        logger.debug("Batch %d/%d: ~%d tokens", i + 1, len(batches), prompt_tokens)

        # Check all daily budgets — skip if any exhausted
        can_proceed, skip_reason = _can_make_request(total_needed)
        if not can_proceed:
            logger.warning("%s budget exhausted, skipping batch %d/%d", skip_reason, i + 1, len(batches))
            budget_exhausted = True
            continue

        # Pace to stay under per-minute limits (RPM + TPM)
        rpm_wait = _check_rpm_budget()
        tpm_wait = _check_tpm_budget(total_needed)
        wait = max(rpm_wait, tpm_wait)
        if wait > 0:
            logger.debug("Pacing: sleeping %.1fs before batch %d/%d", wait, i + 1, len(batches))
            time.sleep(wait)
        elif i > 0:
            time.sleep(_SAFE_WAIT_SECONDS)

        # Try primary model first
        rels = _try_extraction(client, primary_model, symbol, library, user_prompt)
        if rels:
            _record_request(total_needed)
            logger.info("Groq batch %d/%d: extracted %d relationship(s)", i + 1, len(batches), len(rels))
            all_rels.extend(rels)
            continue

        # Fallback to secondary model if primary returned nothing
        if primary_model != _FALLBACK_MODEL:
            logger.info("Groq primary model %s returned nothing, trying fallback %s", primary_model, _FALLBACK_MODEL)
            rels = _try_extraction(client, _FALLBACK_MODEL, symbol, library, user_prompt)
            if rels:
                _record_request(total_needed)
                logger.info("Groq batch %d/%d: extracted %d relationship(s)", i + 1, len(batches), len(rels))
                all_rels.extend(rels)

    return all_rels, budget_exhausted
