from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

RELATIONSHIP_PHRASES = {
    "removed", "deprecated", "replaced", "replaced by", "use instead",
    "renamed", "renamed to", "migrated", "migrated to", "superseded", "superseded by",
    "moved to",
}

DIRECTIONAL_RELATIONS = {
    "replaced_by", "renamed_to", "moved_to", "superseded_by"
}

INVALID_TARGETS = {
    "v1", "v2", "1.0", "latest", "main", "head", "deprecated", "removed",
    "upgrade", "migration", "replacement", "none", "null", "true", "false", ""
}

def is_likely_symbol(target: str) -> bool:
    """
    Validates if a target string resembles a code symbol rather than a generic word.
    """
    if not target or len(target) < 3:
        return False
        
    target_lower = target.lower()
    
    if target_lower in INVALID_TARGETS:
        return False
        
    if " " in target:
        return False
        
    # Reject pure version numbers like "1.0", "v1.2.3"
    if re.fullmatch(r"v?\d+(\.\d+)*", target_lower):
        return False
        
    # Must contain either a dot (path) or underscore (snake_case)
    # Exceptions exist but this captures 99% of valid cross-module references
    if "." not in target and "_" not in target:
        # Check for PascalCase / camelCase
        if target.islower() or target.isupper():
            return False
            
    return True

def validate_relationship(relationship: dict, source_text: str) -> tuple[bool, str | None]:
    """
    Verification before Mongo write:
    1. Source URL exists (already checked if we got source_text)
    2. Old symbol (`from`) appears in source text
    3. New symbol (`to`) appears in source text
    4. A relationship phrase exists in source text
    5. Target symbol is valid

    Fallback relationships from the curated database bypass text-grounding
    checks — they are pre-verified and do not depend on web-scraped evidence.
    """
    # Fallback relationships are pre-verified from curated database — skip text checks
    if relationship.get("extraction_method") == "fallback":
        return True, None

    old_symbol = relationship.get("from", "")
    new_symbol = relationship.get("to", "")
    relation = relationship.get("relation", "")
    
    if not old_symbol or not new_symbol:
        msg = f"Validation failed: missing from/to in relationship {relationship}"
        logger.debug(msg)
        return False, "missing_from_or_to"
        
    if not is_likely_symbol(new_symbol):
        msg = f"Validation failed: invalid target symbol '{new_symbol}'"
        logger.debug(msg)
        return False, "invalid_target"
            
    text_lower = source_text.lower()
    
    # 2. Old symbol appears
    # Extract the last part of the symbol for looser matching since the full dotted path might not be used
    old_parts = old_symbol.split(".")
    old_tail = old_parts[-1].lower() if old_parts else ""
    if old_tail and old_tail not in text_lower:
        msg = f"Validation failed: old symbol '{old_tail}' not found in source text"
        logger.debug(msg)
        return False, "old_symbol_not_found"
        
    # 3. New symbol appears
    new_parts = new_symbol.split(".")
    new_tail = new_parts[-1].lower() if new_parts else ""
    if new_tail and new_tail not in text_lower:
        msg = f"Validation failed: new symbol '{new_tail}' not found in source text"
        logger.debug(msg)
        return False, "new_symbol_not_found"
        
    # 4. Relationship phrase exists (bypass for regex and fallback methods)
    if relationship.get("extraction_method") not in ("regex", "fallback"):
        if not any(phrase in text_lower for phrase in RELATIONSHIP_PHRASES):
            msg = f"Validation failed: no relationship phrase found in source text"
            logger.debug(msg)
            return False, "no_relationship_phrase"
        
    return True, None
