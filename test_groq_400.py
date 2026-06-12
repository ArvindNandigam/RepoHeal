"""
Test script to diagnose Groq API HTTP 400 errors.
Tests the exact request payload used in the production code.
"""
import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from app.config import get_settings
from groq import Groq
from groq.types.chat import ChatCompletion

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

IMPORTANT: Use the FULL dotted path for both "from" and "to" fields (e.g. "pandas.DataFrame.append", not just "append").
Valid relations: "deprecated_in_favor_of", "deprecated_in", "removed_in", "replaced_by", "renamed_to", "moved_to", "superseded_by".
Use "deprecated_in_favor_of" when the old symbol is deprecated and a replacement is explicitly mentioned. Use "deprecated_in" when a deprecation version is stated. Use "removed_in" when removal is explicitly stated.
"""

def make_groq_request(library: str, symbol: str, snippets: list[str], source_context: list[dict]):
    """Exactly replicates the production code's request."""
    api_key = settings.groq_api_key
    model = settings.groq_model
    
    print(f"\n{'='*60}")
    print(f"Testing Groq API call")
    print(f"{'='*60}")
    print(f"Model: {model}")
    print(f"API Key set: {bool(api_key)}")
    print(f"Library: {library}")
    print(f"Symbol: {symbol}")
    print(f"Snippets count: {len(snippets)}")
    print(f"Source context count: {len(source_context)}")
    
    if not api_key:
        print("ERROR: GROQ_API_KEY not set")
        return None
    
    client = Groq(api_key=api_key)
    
    combined_snippets = "\n\n---\n\n".join(snippets[:10])
    context_str = json.dumps(
        [{"title": c.get("title"), "url": c.get("url")} for c in source_context],
        indent=2
    )
    user_prompt = (
        f"Target symbol: {symbol}\n"
        f"Library: {library}\n\n"
        f"Ranked Sources:\n{context_str}\n\n"
        f"Snippets:\n{combined_snippets}"
    )
    
    # Build the exact request body
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }
    
    # Print request summary
    sys_prompt_len = len(SYSTEM_PROMPT)
    user_prompt_len = len(user_prompt)
    total_chars = sys_prompt_len + user_prompt_len
    print(f"\nSystem prompt length: {sys_prompt_len} chars")
    print(f"User prompt length: {user_prompt_len} chars")
    print(f"Total prompt length: {total_chars} chars")
    print(f"\nRequest Payload (summary):")
    print(f"  response_format: {json.dumps(request_body['response_format'])}")
    print(f"  temperature: {request_body['temperature']}")
    print(f"  messages[0].content length: {len(request_body['messages'][0]['content'])}")
    print(f"  messages[1].content length: {len(request_body['messages'][1]['content'])}")
    
    # Now try 3 variants to diagnose
    variants = [
        ("With json_object", {"type": "json_object"}),
        ("No response_format", None),
        ("With json_schema (strict=false)", {
            "type": "json_schema",
            "json_schema": {
                "name": "relationships",
                "strict": False,
                "schema": {
                    "type": "object",
                    "properties": {
                        "relationships": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from": {"type": "string"},
                                    "relation": {
                                        "type": "string",
                                        "enum": [
                                            "deprecated_in_favor_of", "deprecated_in",
                                            "removed_in", "replaced_by",
                                            "renamed_to", "moved_to", "superseded_by"
                                        ]
                                    },
                                    "to": {"type": "string"},
                                    "confidence": {"type": "number"}
                                },
                                "required": ["from", "relation", "to", "confidence"]
                            }
                        }
                    },
                    "required": ["relationships"]
                }
            }
        })
    ]
    
    for variant_name, resp_fmt in variants:
        print(f"\n--- Variant: {variant_name} ---")
        try:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0,
            }
            if resp_fmt:
                body["response_format"] = resp_fmt
            
            completion = client.chat.completions.create(**body)
            response_text = completion.choices[0].message.content
            print(f"SUCCESS! Response received.")
            print(f"Response length: {len(response_text)} chars")
            
            parsed = json.loads(response_text)
            rels = parsed.get("relationships", [])
            print(f"Relationships found: {len(rels)}")
            if rels:
                print(f"First relationship: {json.dumps(rels[0], indent=2)}")
            
            # If json_object works, return this variant
            if resp_fmt and resp_fmt.get("type") == "json_object":
                print("\n*** json_object mode works! ***")
                return {
                    "variant": variant_name,
                    "success": True,
                    "relationships": rels,
                    "response_text": response_text
                }
                
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            # Try to get more details
            if hasattr(e, 'status_code'):
                print(f"  Status code: {e.status_code}")
            if hasattr(e, 'body'):
                print(f"  Response body: {e.body}")
            if hasattr(e, 'response'):
                try:
                    response_body = e.response.text if hasattr(e.response, 'text') else str(e.response)
                    print(f"  Full response: {response_body[:500]}")
                except:
                    pass
    
    return None


def test_with_real_data():
    """Test with simulated search data for pandas.DataFrame.append."""
    snippets = [
        "pandas.DataFrame.append was deprecated in version 1.4.0. Use pandas.concat instead.",
        "Warning: DataFrame.append is deprecated since pandas 1.4.0. Use DataFrame.append is deprecated, use pandas.concat instead.",
        "The append method of DataFrame has been deprecated since pandas 1.4.0 and will be removed in a future version. The recommended replacement is pandas.concat.",
        "Deprecated since version 1.4.0: DataFrame.append has been deprecated. Use concat() instead.",
        "For merging DataFrames, use pandas.concat() instead of DataFrame.append(). append() was deprecated in pandas 1.4.0.",
        "When appending rows, prefer pandas.concat() over the deprecated DataFrame.append() method.",
    ]
    
    source_context = [
        {"title": "pandas.DataFrame.append - pandas documentation", "url": "https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.append.html"},
        {"title": "What's new in pandas 1.4.0", "url": "https://pandas.pydata.org/docs/whatsnew/v1.4.0.html"},
        {"title": "pandas concat vs append", "url": "https://stackoverflow.com/questions/1234/pandas-concat-vs-append"},
    ]
    
    return make_groq_request("pandas", "pandas.DataFrame.append", snippets, source_context)


def test_long_snippets():
    """Test with very long snippets to see if token limit is the issue."""
    long_snippets = [
        "pandas.DataFrame.append was deprecated in version 1.4.0. Use pandas.concat instead. " * 500  # ~40K chars
    ]
    source_context = [
        {"title": "Test", "url": "https://example.com"}
    ]
    return make_groq_request("pandas", "pandas.DataFrame.append", long_snippets, source_context)


if __name__ == "__main__":
    print("=" * 60)
    print("GROQ API 400 DIAGNOSTIC TEST")
    print("=" * 60)
    print(f"Groq SDK version: {Groq.__module__}")
    print(f"Env GROQ_MODEL: {settings.groq_model}")
    print(f"Env GROQ_API_KEY set: {bool(settings.groq_api_key)}")
    
    # Test 1: Normal request
    print("\n\n>>> TEST 1: Normal request with pandas.DataFrame.append")
    result1 = test_with_real_data()
    
    # Test 2: Very long snippets (potential token limit issue)
    print("\n\n>>> TEST 2: Long snippets (token limit test)")
    result2 = test_long_snippets()
    
    print("\n\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
