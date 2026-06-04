from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

def normalize_symbol(raw: str) -> str:
    """
    Strips trailing parens, punctuation, markdown formatting, and whitespace.
    """
    s = raw.strip()
    # Remove all markdown formatting characters like backticks or asterisks
    s = re.sub(r"[`*'\"]", "", s)
    s = s.rstrip("();:,!?")
    return s.strip()

def is_valid_symbol(s: str) -> bool:
    """
    Must contain a dot (or be a recognized method call).
    Must not be a common generic word.
    """
    if not s or len(s) < 3:
        return False
    if " " in s:
        # If it has spaces, it's not a single symbol, unless it's just trailing parens
        if not (s.endswith("()") and s.count(" ") == 1):
            return False
    if "." not in s:
        return False
    return True

def extract_arrow_patterns(text: str) -> list[dict]:
    """
    Extracts patterns like:
    A -> B
    A replaced by B
    etc.
    """
    relationships = []
    
    # Common transition phrases
    phrases = [
        r"->", r"→", r"replaced\s+by", r"renamed\s+to", r"migrated\s+to", 
        r"use\s+([^\s]+)\s+instead", r"should\s+be\s+replaced\s+with", 
        r"is\s+no\s+longer\s+supported;?\s+use", r"superseded\s+by", 
        r"becomes", r"replaced\s+with"
    ]
    
    for phrase in phrases:
        # Match "Symbol A [phrase] Symbol B"
        # Exception: "use B instead (of A)" has a different order, but the regex above matches "use B instead"
        if "instead" in phrase:
             # Let's use a broader regex for all phrases for simplicity: 
             # just find the phrase, grab token before and token after
             pass
        
    # Better approach: precise regexes for A -> B
    # A -> B, A → B, A replaced by B, A renamed to B, A migrated to B, A superseded by B, A becomes B, A replaced with B
    forward_phrases = r"(?:->|→|(?:was\s+|is\s+|has\s+been\s+)?replaced\s+by|(?:was\s+|is\s+|has\s+been\s+)?renamed\s+to|(?:was\s+|is\s+|has\s+been\s+)?migrated\s+to|(?:was\s+|is\s+|has\s+been\s+)?superseded\s+by|becomes|(?:was\s+|is\s+|has\s+been\s+)?replaced\s+with|should\s+be\s+replaced\s+with|is\s+no\s+longer\s+supported;?\s*use)"
    
    pattern = rf"([a-zA-Z0-9_\.]+)\s*(?:\(\))?\s*{forward_phrases}\s*([a-zA-Z0-9_\.]+)(?:\(\))?"
    
    for match in re.finditer(pattern, text, re.IGNORECASE):
        from_sym = normalize_symbol(match.group(1))
        to_sym = normalize_symbol(match.group(2))
        
        if is_valid_symbol(from_sym) and is_valid_symbol(to_sym) and from_sym != to_sym:
            relationships.append({
                "from": from_sym,
                "relation": "replaced_by",
                "to": to_sym,
                "confidence": 1.0,
                "extraction_method": "regex"
            })
            
    # "use B instead of A" or "use B instead"
    use_pattern = r"use\s+([a-zA-Z0-9_\.]+)(?:\(\))?\s+instead(?:\s+of\s+([a-zA-Z0-9_\.]+)(?:\(\))?)?"
    for match in re.finditer(use_pattern, text, re.IGNORECASE):
        to_sym = normalize_symbol(match.group(1))
        from_sym = normalize_symbol(match.group(2)) if match.group(2) else None
        
        if to_sym and is_valid_symbol(to_sym):
            if from_sym and is_valid_symbol(from_sym) and from_sym != to_sym:
                relationships.append({
                    "from": from_sym,
                    "relation": "replaced_by",
                    "to": to_sym,
                    "confidence": 1.0,
                    "extraction_method": "regex"
                })
            # If from_sym is not in the regex but we have target symbol, we can't easily extract the from_sym from context with simple regex.
            # We rely on extract_relationships_regex passing the target_symbol down.

    return relationships

def extract_migration_table(text: str, target_symbol: str) -> list[dict]:
    """
    Detects adjacent symbols where one is the target symbol.
    """
    relationships = []
    
    lines = [line.strip() for line in text.split("\n")]
    for i in range(len(lines) - 1):
        line1 = normalize_symbol(lines[i])
        line2 = normalize_symbol(lines[i+1])
        
        # Check if they are valid symbols and one is the target
        # And there is no prose (they are just symbols)
        if line1 == target_symbol and is_valid_symbol(line2) and line1 != line2:
            relationships.append({
                "from": line1,
                "relation": "replaced_by",
                "to": line2,
                "confidence": 1.0,
                "extraction_method": "regex"
            })
        elif line2 == target_symbol and is_valid_symbol(line1) and line1 != line2:
             relationships.append({
                "from": line1,
                "relation": "replaced_by",
                "to": line2,
                "confidence": 1.0,
                "extraction_method": "regex"
            })
            
    return relationships

def extract_relationships_regex(symbol: str, library: str, snippets: list[str]) -> list[dict]:
    """
    Runs deterministic extraction.
    """
    results = []
    seen = set()
    
    for snippet in snippets:
        # Arrow/prose patterns
        rels = extract_arrow_patterns(snippet)
        for rel in rels:
            # If the from_sym in the relation is related to our target symbol
            # or if we found a relation
            key = (rel["from"], rel["relation"], rel["to"])
            if key not in seen:
                results.append(rel)
                seen.add(key)
                
        # Migration tables
        rels_table = extract_migration_table(snippet, symbol)
        for rel in rels_table:
            key = (rel["from"], rel["relation"], rel["to"])
            if key not in seen:
                results.append(rel)
                seen.add(key)
                
    return results
