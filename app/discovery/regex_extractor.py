from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_VERSION_NUM_RE = re.compile(r"^v?\d+(\.\d+)*$")
_PROSE_WITH_DOTS = {
    "deprecated.since", "removed.in", "replaced.by", "use.instead",
    "none.null", "true.false", "version.x", "see.also", "note.that",
    "e.g", "i.e", "et.al", "w.r.t",
}

def normalize_symbol(raw: str) -> str:
    """
    Strips trailing parens, punctuation, markdown formatting, and whitespace.
    """
    s = raw.strip()
    s = re.sub(r"[`*'\"]", "", s)
    s = s.rstrip(".;():,!?")
    return s.strip()

def is_valid_symbol(s: str) -> bool:
    """
    Must contain a dot (or be a recognized method call).
    Must not be a common generic word, version number, or prose fragment.
    """
    if not s or len(s) < 3:
        return False
    if " " in s:
        if not (s.endswith("()") and s.count(" ") == 1):
            return False
    if "." not in s:
        return False
    # Reject pure version numbers: 1.0, v1.2.3, 2.0.0rc1, etc.
    if _VERSION_NUM_RE.match(s):
        return False
    # Reject known prose fragments
    if s.lower() in _PROSE_WITH_DOTS:
        return False
    # Reject if both parts of "a.b" are version-like or purely numeric
    parts = s.split(".")
    if all(_VERSION_NUM_RE.match(p) for p in parts[:2]):
        return False
    return True

def _normalize_text_for_matching(text: str) -> str:
    """
    Preprocess text to handle line breaks and sentence boundaries in
    deprecation patterns:

    - "is deprecated.\nUse Y" -> "is deprecated. use Y"
    - "is deprecated. Please use Y" -> "is deprecated. use Y"
    - "is deprecated.\n\nYou should use Y" -> "is deprecated. use Y"
    """
    s = text
    # Collapse line breaks within sentences (replace newline+spaces with space)
    s = re.sub(r"\n\s*", " ", s)
    # Normalize "deprecated. Use" / "deprecated. Please use" / "deprecated. You should use"
    s = re.sub(
        r"deprecated\.\s+(Please\s+|You\s+should\s+)?(use|consider)",
        "deprecated, use",
        s,
        flags=re.IGNORECASE,
    )
    # Normalize "removed. Use" -> "removed, use"
    s = re.sub(
        r"removed\.\s+(Please\s+|You\s+should\s+)?(use|consider)",
        "removed, use",
        s,
        flags=re.IGNORECASE,
    )
    return s


def extract_arrow_patterns(text: str) -> list[dict]:
    """
    Extracts patterns like:
    A -> B
    A replaced by B
    A is deprecated, use B
    A deprecated in favor of B
    A is deprecated. Use B instead (spanning sentences/line breaks)
    etc.
    """
    relationships = []
    text = _normalize_text_for_matching(text)

    # Patterns for deprecation language
    deprecated_phrases = r"(?:is\s+)?deprecated\s*,?\s*(?:since\s+[\d.]+\s*[,;]?\s*)?(?:in\s+favor\s+of\s+|\.\s*use\s+|,\s*use\s+|;?\s*use\s+|\.\s*please\s+use\s+)"
    deprecated_pattern = rf"([a-zA-Z0-9_\.]+)\s*(?:\(\))?\s*{deprecated_phrases}\s*([a-zA-Z0-9_\.]+)(?:\(\))?"
    for match in re.finditer(deprecated_pattern, text, re.IGNORECASE):
        from_sym = normalize_symbol(match.group(1))
        to_sym = normalize_symbol(match.group(2))
        if is_valid_symbol(from_sym) and is_valid_symbol(to_sym) and from_sym != to_sym:
            relationships.append({
                "from": from_sym,
                "relation": "deprecated_in_favor_of",
                "to": to_sym,
                "confidence": 1.0,
                "extraction_method": "regex"
            })

    # "deprecated since version X" — marks the deprecation version, no replacement
    dep_version_phrases = r"(?:is\s+)?deprecated\s+(?:as\s+of|since|from)\s+version\s+([\d.]+)"
    dep_version_pattern = rf"([a-zA-Z0-9_\.]+)\s*(?:\(\))?\s*{dep_version_phrases}"
    for match in re.finditer(dep_version_pattern, text, re.IGNORECASE):
        from_sym = normalize_symbol(match.group(1))
        ver_sym = normalize_symbol(match.group(2))
        if is_valid_symbol(from_sym):
            relationships.append({
                "from": from_sym,
                "relation": "deprecated_in",
                "to": ver_sym,
                "confidence": 1.0,
                "extraction_method": "regex"
            })

    # "removed in version X"
    removed_phrases = r"(?:is\s+)?removed\s+(?:as\s+of|since|from|in)\s+(?:version\s+)?([\d.]+)"
    removed_pattern = rf"([a-zA-Z0-9_\.]+)\s*(?:\(\))?\s*{removed_phrases}"
    for match in re.finditer(removed_pattern, text, re.IGNORECASE):
        from_sym = normalize_symbol(match.group(1))
        ver_sym = normalize_symbol(match.group(2))
        if is_valid_symbol(from_sym):
            relationships.append({
                "from": from_sym,
                "relation": "removed_in",
                "to": ver_sym,
                "confidence": 1.0,
                "extraction_method": "regex"
            })

    # Forward transition patterns
    forward_phrases = r"(?:->|→|(?:was\s+|is\s+|has\s+been\s+)?replaced\s+by|(?:was\s+|is\s+|has\s+been\s+)?renamed\s+to|(?:was\s+|is\s+|has\s+been\s+)?migrated\s+to|(?:was\s+|is\s+|has\s+been\s+)?superseded\s+by|becomes|(?:was\s+|is\s+|has\s+been\s+)?replaced\s+with|should\s+be\s+replaced\s+with|is\s+no\s+longer\s+supported;?\s*use)"

    pattern = rf"([a-zA-Z0-9_\.]+)\s*(?:\(\))?\s*{forward_phrases}\s*([a-zA-Z0-9_\.]+)(?:\(\))?"

    for match in re.finditer(pattern, text, re.IGNORECASE):
        from_sym = normalize_symbol(match.group(1))
        to_sym = normalize_symbol(match.group(2))

        if is_valid_symbol(from_sym) and is_valid_symbol(to_sym) and from_sym != to_sym:
            relationships.append({
                "from": from_sym,
                "relation": "deprecated_in_favor_of",
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

    # "instead of A, use B" pattern
    instead_pattern = r"instead\s+of\s+([a-zA-Z0-9_\.]+)(?:\(\))?[,;.]*\s+use\s+([a-zA-Z0-9_\.]+)(?:\(\))?"
    for match in re.finditer(instead_pattern, text, re.IGNORECASE):
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
