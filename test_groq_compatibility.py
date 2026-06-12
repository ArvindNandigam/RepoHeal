"""
Test script: Groq API compatibility for migration intelligence.
Tests pandas DataFrame.append and prints raw/parsed response.
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING)

from app.config import get_settings
from groq import Groq, BadRequestError, APIStatusError

settings = get_settings()

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

IMPORTANT: Use the FULL dotted path for both "from" and "to" fields.
Valid relations: "deprecated_in_favor_of", "deprecated_in", "removed_in", "replaced_by", "renamed_to", "moved_to", "superseded_by".
"""

def test_groq_compatibility(library, symbol, snippets, source_context=None):
    """Test Groq API and print detailed results."""
    print(f"\n{'='*70}")
    print(f"LIBRARY: {library}")
    print(f"SYMBOL:  {symbol}")
    print(f"{'='*70}")

    api_key = settings.groq_api_key
    model = settings.groq_model

    if not api_key:
        print("FAIL: GROQ_API_KEY not set")
        return None

    client = Groq(api_key=api_key)
    combined = "\n\n---\n\n".join(snippets[:10])
    ctx = source_context or []
    context_str = json.dumps(
        [{"title": c.get("title"), "url": c.get("url")} for c in ctx], indent=2
    )
    user_prompt = f"Target symbol: {symbol}\nLibrary: {library}\n\nRanked Sources:\n{context_str}\n\nSnippets:\n{combined}"

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }

    total_chars = len(SYSTEM_PROMPT) + len(user_prompt)
    print(f"System prompt: {len(SYSTEM_PROMPT)} chars")
    print(f"User prompt:   {len(user_prompt)} chars")
    print(f"Total input:   {total_chars} chars")
    print(f"Model:         {model}")
    print(f"Response fmt:  json_object")

    try:
        completion = client.chat.completions.create(**request_body)
        response_text = completion.choices[0].message.content

        print(f"\n--- RAW RESPONSE ---")
        print(response_text)

        parsed = json.loads(response_text)
        rels = parsed.get("relationships", [])

        print(f"\n--- PARSED RESPONSE ---")
        print(f"Relationships found: {len(rels)}")
        for r in rels:
            print(f"  {r.get('from')} --[{r.get('relation')}]--> {r.get('to')} (confidence: {r.get('confidence')})")

        print(f"\n--- DETECTED DEPRECATIONS ---")
        deprecations = [r for r in rels if 'deprecated' in r.get('relation', '')]
        for d in deprecations:
            print(f"  {d.get('from')} is {d.get('relation')} -> {d.get('to')}")

        print(f"\n--- MIGRATION RECOMMENDATIONS ---")
        migrations = [r for r in rels if r.get('relation') in ('replaced_by', 'deprecated_in_favor_of', 'renamed_to', 'moved_to', 'superseded_by')]
        for m in migrations:
            print(f"  Replace {m.get('from')} with {m.get('to')}")

        return rels

    except BadRequestError as e:
        print(f"\n--- ERROR: HTTP {e.status_code} ---")
        print(f"Message: {e.message}")
        if isinstance(e.body, dict):
            err = e.body.get("error", {})
            print(f"Error type: {err.get('type')}")
            print(f"Error message: {err.get('message')}")
        return None
    except APIStatusError as e:
        print(f"\n--- ERROR: HTTP {e.status_code} ---")
        print(f"Message: {e.message}")
        return None
    except Exception as e:
        print(f"\n--- ERROR: {type(e).__name__} ---")
        print(f"Message: {e}")
        return None


if __name__ == "__main__":
    print("=" * 70)
    print("GROQ API COMPATIBILITY TEST")
    print(f"Groq SDK: groq=={Groq.__module__}")
    print(f"Model: {settings.groq_model}")
    print(f"API Key: {'set' if settings.groq_api_key else 'NOT SET'}")
    print("=" * 70)

    # Test 1: pandas.DataFrame.append
    test_groq_compatibility(
        library="pandas",
        symbol="pandas.DataFrame.append",
        snippets=[
            "pandas.DataFrame.append was deprecated in version 1.4.0. Use pandas.concat instead.",
            "Deprecated since version 1.4.0: DataFrame.append has been deprecated. Use concat() instead.",
            "Warning: DataFrame.append is deprecated since pandas 1.4.0. The recommended replacement is pandas.concat.",
        ],
        source_context=[
            {"title": "pandas docs", "url": "https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.append.html"},
        ]
    )

    # Test 2: numpy.ndarray.tolist (no deprecation - should return empty)
    test_groq_compatibility(
        library="numpy",
        symbol="numpy.ndarray.tolist",
        snippets=[
            "numpy.ndarray.tolist converts an array to a list.",
            "numpy.ndarray.tolist() returns a copy of the array data as a Python list.",
        ],
        source_context=[
            {"title": "numpy docs", "url": "https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tolist.html"},
        ]
    )

    # Test 3: requests.RequestException
    test_groq_compatibility(
        library="requests",
        symbol="requests.RequestException",
        snippets=[
            "requests.RequestException is the base exception class for the requests library.",
            "All exceptions in requests inherit from requests.RequestException.",
        ],
        source_context=[
            {"title": "requests docs", "url": "https://docs.python-requests.org/en/latest/api/#requests.RequestException"},
        ]
    )

    # Test 4: Token limit edge case - very large content
    print(f"\n{'='*70}")
    print("TEST: Token limit edge case (oversized input)")
    print(f"{'='*70}")
    test_groq_compatibility(
        library="pandas",
        symbol="pandas.DataFrame.append",
        snippets=["pandas.DataFrame.append was deprecated. Use pandas.concat instead. " * 50000],
        source_context=[],
    )

    print(f"\n{'='*70}")
    print("TEST COMPLETE")
    print(f"{'='*70}")
