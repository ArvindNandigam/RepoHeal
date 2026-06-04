import os
import sys

# Add app path to sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.discovery.regex_extractor import normalize_symbol, extract_relationships_regex
from app.discovery.validation import is_likely_symbol, validate_relationship
from app.services.migration_engine import _deduplicate_relationships

def test_normalization():
    assert normalize_symbol("ChatCompletion.create()") == "ChatCompletion.create"
    assert normalize_symbol(" `openai.ChatCompletion.create`: ") == "openai.ChatCompletion.create"
    # Underscore preservation check
    assert normalize_symbol("openai.api_base") == "openai.api_base"
    print("Normalization OK")

def test_extraction():
    snippet1 = "openai.ChatCompletion.create() -> client.chat.completions.create()"
    rels1 = extract_relationships_regex("openai.ChatCompletion.create", "openai", [snippet1])
    assert len(rels1) == 1
    assert rels1[0]["to"] == "client.chat.completions.create"
    
    snippet2 = "openai.ChatCompletion.create()\nclient.chat.completions.create()"
    rels2 = extract_relationships_regex("openai.ChatCompletion.create", "openai", [snippet2])
    assert len(rels2) == 1
    assert rels2[0]["to"] == "client.chat.completions.create"

    snippet3 = "openai.ChatCompletion.create() was replaced by client.chat.completions.create()"
    rels3 = extract_relationships_regex("openai.ChatCompletion.create", "openai", [snippet3])
    assert len(rels3) == 1
    assert rels3[0]["to"] == "client.chat.completions.create"
    
    snippet4 = "A -> A"
    rels4 = extract_relationships_regex("A", "lib", [snippet4])
    assert len(rels4) == 0  # Invalid symbol / same
    
    print("Extraction OK")

def test_validation():
    # is_likely_symbol tests
    assert is_likely_symbol("client.chat.completions.create") is True
    assert is_likely_symbol("openai.BadRequestError") is True
    assert is_likely_symbol("some_snake_case") is True
    
    assert is_likely_symbol("v1") is False
    assert is_likely_symbol("1.0") is False
    assert is_likely_symbol("latest") is False
    assert is_likely_symbol("HEAD") is False
    assert is_likely_symbol("migration") is False
    
    # validate_relationship rejection test
    rel = {"from": "X.Y", "relation": "removed_in", "to": "v1"}
    is_valid, reason = validate_relationship(rel, "X.Y was removed in v1")
    assert is_valid is False
    assert reason == "invalid_target"
    print("Validation OK")

def test_deduplication():
    rels = [
        {"from": "A.B", "relation": "replaced_by", "to": "C.D", "confidence": 1.0, "extraction_method": "groq"},
        {"from": "A.B", "relation": "replaced_by", "to": "C.D", "confidence": 1.0, "extraction_method": "regex"},
        {"from": "A.B", "relation": "replaced_by", "to": "C.D", "confidence": 0.5, "extraction_method": "regex"}
    ]
    deduped = _deduplicate_relationships(rels)
    assert len(deduped) == 1
    assert deduped[0]["extraction_method"] == "regex"
    assert deduped[0]["confidence"] == 1.0
    print("Deduplication OK")

if __name__ == "__main__":
    test_normalization()
    test_extraction()
    test_validation()
    test_deduplication()
    
    # Test groq import
    from groq import Groq
    print("Groq imported successfully")

