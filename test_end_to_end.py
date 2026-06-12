"""End-to-end test: pandas.DataFrame.append discovery pipeline (no Groq)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.discovery.regex_extractor import extract_relationships_regex
from app.discovery.fallback_extractor import extract_relationships_fallback
from app.services.migration_engine import _deduplicate_relationships

symbol = "pandas.DataFrame.append"
library = "pandas"

snippets = [
    "pandas.DataFrame.append is deprecated. Use pandas.concat instead.",
    "DataFrame.append was removed in pandas 2.0.",
]

# Phase 1: Regex extraction
regex_rels = extract_relationships_regex(symbol, library, snippets)
print("Regex relationships:")
for r in regex_rels:
    print(f"  {r['from']} --[{r['relation']}]--> {r['to']} (conf={r['confidence']})")

# Phase 2: Fallback extraction (simulates Groq-empty fallback)
fallback_rels = extract_relationships_fallback(symbol, library)
print("Fallback relationships:")
for r in fallback_rels:
    print(f"  {r['from']} --[{r['relation']}]--> {r['to']} (conf={r['confidence']})")

# Phase 3: Dedup across both
all_rels = regex_rels + fallback_rels
deduped = _deduplicate_relationships(all_rels)
print("Deduplicated relationships:")
for r in deduped:
    method = r.get("extraction_method", "?")
    print(f"  {r['from']} --[{r['relation']}]--> {r['to']} (method={method})")

# Verify key results
assert len(deduped) >= 2, f"Expected >=2 deduped rels, got {len(deduped)}"
assert any(r["to"] == "pandas.concat" for r in deduped), "Missing pandas.concat target"
assert any(r["relation"] == "removed_in" for r in deduped), "Missing removed_in relation"
print("\nEnd-to-end test PASSED")
