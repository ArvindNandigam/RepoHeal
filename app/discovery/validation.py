from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RELATIONSHIP_PHRASES = {
    "removed", "deprecated", "replaced", "replaced by", "use instead",
    "renamed", "renamed to", "migrated", "migrated to", "superseded", "superseded by",
    "moved to",
}

def validate_relationship(relationship: dict, source_text: str) -> bool:
    """
    4-point verification before Mongo write:
    1. Source URL exists (already checked if we got source_text)
    2. Old symbol (`from`) appears in source text
    3. New symbol (`to`) appears in source text
    4. A relationship phrase exists in source text
    """
    old_symbol = relationship.get("from", "")
    new_symbol = relationship.get("to", "")
    
    if not old_symbol or not new_symbol:
        logger.warning(f"Validation failed: missing from/to in relationship {relationship}")
        return False
        
    text_lower = source_text.lower()
    
    # 2. Old symbol appears
    # Extract the last part of the symbol for looser matching since the full dotted path might not be used
    old_parts = old_symbol.split(".")
    old_tail = old_parts[-1].lower() if old_parts else ""
    if old_tail and old_tail not in text_lower:
        logger.warning(f"Validation failed: old symbol '{old_tail}' not found in source text")
        return False
        
    # 3. New symbol appears
    new_parts = new_symbol.split(".")
    new_tail = new_parts[-1].lower() if new_parts else ""
    if new_tail and new_tail not in text_lower:
        logger.warning(f"Validation failed: new symbol '{new_tail}' not found in source text")
        return False
        
    # 4. Relationship phrase exists (bypass for regex-extracted migration tables)
    if relationship.get("extraction_method") != "regex":
        if not any(phrase in text_lower for phrase in RELATIONSHIP_PHRASES):
            logger.warning(f"Validation failed: no relationship phrase found in source text")
            return False
        
    return True
