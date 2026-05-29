from __future__ import annotations


LIBRARY_ALIASES = {
    "openai": "openai",
    "pydantic": "pydantic",
    "py dantic": "pydantic",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "scikit-learn": "scikit-learn",
}


def normalize_library_name(library: str) -> str:
    normalized = " ".join(library.strip().lower().replace("_", "-").split())
    return LIBRARY_ALIASES.get(normalized, normalized)


def normalize_symbol_list(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return []

    unique_symbols: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        cleaned = symbol.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_symbols.append(cleaned)
    return unique_symbols
